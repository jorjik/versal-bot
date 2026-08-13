from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from versal.config import settings
from versal.db.models import AppConfig, Event, GuestTicket, TableReservation, User

# Ключи конфига
CFG_GUEST_LIST_LIMIT = "guest_list_limit"
CFG_GUEST_LIST_OPEN = "guest_list_open"
CFG_MENU_FILE_ID = "menu_file_id"
CFG_MENU_KIND = "menu_kind"  # document / photo


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------
async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
) -> User:
    user = await get_user(session, telegram_id)
    if user is None:
        role = "admin" if telegram_id in settings.admin_ids else "staff" if telegram_id in settings.staff_ids else "guest"
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    changed = False
    if username is not None and user.username != username:
        user.username, changed = username, True
    if first_name is not None and user.first_name != first_name:
        user.first_name, changed = first_name, True
    if last_name is not None and user.last_name != last_name:
        user.last_name, changed = last_name, True
    if phone is not None and user.phone != phone:
        user.phone, changed = phone, True
    if changed:
        await session.commit()
    return user


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


def is_blocked_for_guest_list(user: User, now: datetime | None = None) -> bool:
    """True, если пользователь в блокировке Guest List. Просроченную блокировку снимает."""
    if not user.is_blocked_guest_list:
        return False
    now = now or datetime.now()
    if user.blocked_until and user.blocked_until > now:
        return True
    user.is_blocked_guest_list = False
    user.blocked_until = None
    return False


# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------
async def get_config(session: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = await session.get(AppConfig, key)
    return row.value if row and row.value is not None else default


async def set_config(session: AsyncSession, key: str, value: str | None) -> None:
    row = await session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def get_guest_list_limit(session: AsyncSession) -> int:
    raw = await get_config(session, CFG_GUEST_LIST_LIMIT, str(settings.guest_list_limit))
    try:
        return int(raw) if raw else settings.guest_list_limit
    except ValueError:
        return settings.guest_list_limit


async def is_guest_list_open(session: AsyncSession) -> bool:
    raw = await get_config(session, CFG_GUEST_LIST_OPEN)
    if raw is None:
        return True  # по умолчанию открыт
    return raw == "1"


# ---------------------------------------------------------------------------
# Guest List / билеты
# ---------------------------------------------------------------------------
async def active_tickets_today(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(GuestTicket)
        .where(GuestTicket.status == "active", GuestTicket.party_date == date.today())
    ) or 0


async def active_ticket_for_user_today(session: AsyncSession, user: User) -> GuestTicket | None:
    return await session.scalar(
        select(GuestTicket).where(
            GuestTicket.user_id == user.id,
            GuestTicket.status == "active",
            GuestTicket.party_date == date.today(),
        )
    )


async def create_ticket(session: AsyncSession, user: User, token: str | None = None) -> GuestTicket:
    """Создаёт билет (flush, БЕЗ commit — коммит делает вызывающий код,
    чтобы проверка лимита и вставка были в одной транзакции)."""
    import uuid

    from versal.services.security import make_ticket_token

    # Уникальный плейсхолдер: два одновременных запроса разных гостей
    # не должны конфликтовать по UNIQUE-ограничению token.
    ticket = GuestTicket(user_id=user.id, token=token or f"pending-{uuid.uuid4().hex}")
    session.add(ticket)
    await session.flush()
    if token is None:
        # Без refresh: перечитывание из БД затёрло бы токен плейсхолдером
        # (строка ещё не закоммичена). id и token уже есть в памяти.
        ticket.token = make_ticket_token(ticket.id)
    return ticket


async def try_create_ticket_atomic(session: AsyncSession, user: User) -> GuestTicket | None:
    """Атомарно создаёт квиток с учётом лимита.

    На PostgreSQL строка конфига лимита берётся с FOR UPDATE — одновременные
    подтверждения сериализуются, лимит не превышается. На SQLite FOR UPDATE
    игнорируется (это dev-база; продакшен — Postgres).
    """
    limit_row = await session.get(AppConfig, CFG_GUEST_LIST_LIMIT, with_for_update=True)
    raw = limit_row.value if limit_row else None
    try:
        limit = int(raw) if raw else settings.guest_list_limit
    except ValueError:
        limit = settings.guest_list_limit

    if await active_tickets_today(session) >= limit:
        return None

    ticket = await create_ticket(session, user)
    await session.commit()
    return ticket


def apply_miss(user: User) -> bool:
    """Учитывает один пропуск («мёртвая душа»). Возвращает True,
    если пользователь только что заблокирован на 30 дней."""
    user.missed_tickets += 1
    if user.missed_tickets >= settings.missed_tickets_to_block and not user.is_blocked_guest_list:
        user.is_blocked_guest_list = True
        user.blocked_until = datetime.now() + timedelta(days=settings.block_days)
        return True
    return False


async def sweep_missed_tickets(session: AsyncSession) -> int:
    """Метёт «мёртвые души»: билеты за прошлые дни, оставшиеся active, помечаем expired
    и считаем их как неявку. После N неявок пользователь блокируется на 30 дней."""
    today = date.today()
    tickets = (
        await session.execute(
            select(GuestTicket).where(GuestTicket.status == "active", GuestTicket.party_date < today)
        )
    ).scalars().all()

    missed_by_user: dict[int, int] = {}
    for ticket in tickets:
        ticket.status = "expired"
        missed_by_user[ticket.user_id] = missed_by_user.get(ticket.user_id, 0) + 1

    blocked = 0
    for user_id, misses in missed_by_user.items():
        user = await session.get(User, user_id)
        if user is None:
            continue
        for _ in range(misses):
            if apply_miss(user):
                blocked += 1
    await session.commit()
    return blocked


async def ensure_defaults(session: AsyncSession) -> None:
    """Создаёт строки конфига по умолчанию (для FOR UPDATE-блокировки лимита)."""
    for key, value in ((CFG_GUEST_LIST_LIMIT, str(settings.guest_list_limit)),):
        row = await session.get(AppConfig, key)
        if row is None:
            session.add(AppConfig(key=key, value=value))
    await session.commit()


# ---------------------------------------------------------------------------
# Афиша / меню / брони / статистика
# ---------------------------------------------------------------------------
async def list_active_events(session: AsyncSession, limit: int = 5) -> list[Event]:
    stmt = select(Event).where(Event.is_active == True).order_by(Event.starts_at.is_(None), Event.starts_at.asc(), Event.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    return await session.get(Event, event_id)


async def create_event(session: AsyncSession, **kwargs) -> Event:
    event = Event(**kwargs)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def list_reservations(session: AsyncSession, limit: int = 10) -> list[TableReservation]:
    stmt = (
        select(TableReservation)
        .order_by(TableReservation.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_reservation(
    session: AsyncSession,
    user: User,
    date_text: str,
    guests_count: int,
    wishes: str | None,
) -> TableReservation:
    reservation = TableReservation(
        user_id=user.id, date_text=date_text, guests_count=guests_count, wishes=wishes
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)
    return reservation


async def seed_sample_event(session: AsyncSession) -> None:
    """Демо-событие при первом запуске, чтобы афиша не была пустой."""
    count = await session.scalar(select(func.count()).select_from(Event)) or 0
    if count:
        return
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    session.add(
        Event(
            title="Відкриття сезону 🎉",
            description="Тематична вечірка + живий звук. Чекаємо на вас!",
            starts_at=tomorrow,
            price="Вхід 300 грн (після 20:00)",
        )
    )
    await session.commit()


async def list_blocked_users(session: AsyncSession) -> list[User]:
    stmt = select(User).where(User.is_blocked_guest_list == True).order_by(User.blocked_until.desc())
    return list((await session.execute(stmt)).scalars().all())


async def unblock_user(session: AsyncSession, telegram_id: int) -> User | None:
    user = await get_user(session, telegram_id)
    if user is None:
        return None
    user.is_blocked_guest_list = False
    user.blocked_until = None
    user.missed_tickets = 0
    await session.commit()
    return user
