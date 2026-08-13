"""Смоук-тест без Telegram: проверяет БД, подпись токенов, sweep «мёртвых душ».

Запуск:  .venv/Scripts/python scripts/smoke_test.py
"""

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Тест работает с отдельной временной БД, чтобы не трогать данные бота.
_SMOKE_DB = Path(__file__).resolve().parent.parent / "data" / "smoke_test.db"
if _SMOKE_DB.exists():
    _SMOKE_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_SMOKE_DB.as_posix()}"

from versal.config import settings
from versal.db.base import SessionLocal, init_db
from versal.db.repo import (
    CFG_GUEST_LIST_LIMIT,
    active_tickets_today,
    create_ticket,
    ensure_defaults,
    get_or_create_user,
    is_blocked_for_guest_list,
    seed_sample_event,
    set_config,
    sweep_missed_tickets,
    try_create_ticket_atomic,
    unblock_user,
)
from versal.db.models import GuestTicket, User
from versal.services.assets import qr_deep_link
from versal.services.security import make_ticket_token, parse_ticket_token, telegram_start_param

settings.ensure_dirs()


async def main() -> None:
    await init_db()
    async with SessionLocal() as session:
        await seed_sample_event(session)

        # --- пользователи -------------------------------------------------
        guest = await get_or_create_user(session, 100500, username="guest", first_name="Гість", phone="+380000000001")
        staff = await get_or_create_user(session, 100501, username="staff", phone="+380000000002")
        assert guest.role == "guest", guest.role
        assert staff.role == "guest", staff.role  # staff вне env-списка

        # --- токены --------------------------------------------------------
        ticket = await create_ticket(session, guest)
        parsed = parse_ticket_token(ticket.token)
        assert parsed == ticket.id, (parsed, ticket.id)
        assert "_" in ticket.token and "." not in ticket.token, ticket.token
        # Старый формат с точкой (до фикса deep-link) тоже должен парситься.
        assert parse_ticket_token(ticket.token.replace("_", ".")) == ticket.id
        assert parse_ticket_token("1.bad") is None
        assert parse_ticket_token("1_bad") is None
        assert parse_ticket_token("abc.def") is None
        assert parse_ticket_token("") is None
        start_param = telegram_start_param(ticket.token)
        assert start_param.startswith("gl_")
        assert all(c.isalnum() or c in "_-" for c in start_param), start_param
        assert len(start_param) <= 64
        # Даже если в БД лежит старый токен с точкой — в ссылку идёт безопасный вариант.
        old_style_url = qr_deep_link("demo_nightclub_bot", ticket.token.replace("_", "."))
        assert "." not in old_style_url.split("?start=", 1)[1]
        print(f"  OK токен подписан и распознаётся: {ticket.token}")

        # --- лимит/счётчик -------------------------------------------------
        count = await active_tickets_today(session)
        assert count >= 1, count
        print(f"  OK активных билетов сегодня: {count}")

        # --- sweep «мёртвых душ» -------------------------------------------
        old_ticket = GuestTicket(
            user_id=guest.id,
            token=make_ticket_token(999999),
            party_date=date.today() - timedelta(days=1),
            status="active",
        )
        session.add(old_ticket)
        await session.commit()
        blocked = await sweep_missed_tickets(session)
        await session.refresh(guest)
        assert old_ticket.status == "expired"
        assert guest.missed_tickets >= 1, guest.missed_tickets
        print(f"  OK sweep: старый билет помечен expired, пропусков: {guest.missed_tickets}, блокировок: {blocked}")

        # --- блокировка после 3 пропусков -----------------------------------
        guest.missed_tickets = 3
        await session.commit()
        assert is_blocked_for_guest_list(guest) is False  # ещё не заблокирован (флаг не стоит)
        guest.is_blocked_guest_list = True
        guest.blocked_until = datetime.now() + timedelta(days=30)
        await session.commit()
        assert is_blocked_for_guest_list(guest) is True
        print("  OK блокировка Guest List работает")

        # --- разблокировка --------------------------------------------------
        await unblock_user(session, guest.telegram_id)
        await session.refresh(guest)
        assert not guest.is_blocked_guest_list and guest.missed_tickets == 0
        print("  OK разблокировка работает")

        # --- атомарная запись с лимитом ------------------------------------------
        await ensure_defaults(session)
        await set_config(session, CFG_GUEST_LIST_LIMIT, "1")
        blocked_ticket = await try_create_ticket_atomic(session, staff)
        assert blocked_ticket is None, "при лимите 1 и уже активном квитке — запись невозможна"
        await set_config(session, CFG_GUEST_LIST_LIMIT, "100")
        new_ticket = await try_create_ticket_atomic(session, staff)
        assert new_ticket is not None, "при лимите 100 запись должна пройти"
        print("  OK атомарная запись с лимитом работает")

        # --- авто-распознавание deep-link (search=True, не match!) -------------
        from magic_filter import F

        gl_filter = F.text.regexp(r"(?:gl_)?\d+[._][0-9a-f]{16}", search=True)

        class _T:
            def __init__(self, text):
                self.text = text

        url = qr_deep_link("demo_nightclub_bot", ticket.token)
        assert "?start=gl_" in url and "." not in url.split("?start=", 1)[1]
        assert bool(gl_filter.resolve(_T(url))) is True, "URL-ссылка должна распознаваться"
        assert bool(gl_filter.resolve(_T(ticket.token))) is True, "голый токен должен распознаваться"
        # Старая ссылка с точкой (если вставили в чат вручную) тоже распознаётся
        old_url = f"https://t.me/demo_nightclub_bot?start=gl_{ticket.token.replace('_', '.')}"
        assert bool(gl_filter.resolve(_T(old_url))) is True, "старая URL с точкой должна распознаваться"
        assert bool(gl_filter.resolve(_T("привет, как дела?"))) is False, "обычный текст не должен срабатывать"
        print("  OK авто-распознавание deep-link (search=True) работает")

    print("\nSMOKE OK — вся логика работает без Telegram.")


if __name__ == "__main__":
    asyncio.run(main())
