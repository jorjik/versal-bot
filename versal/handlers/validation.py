from __future__ import annotations

import re
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from versal.config import settings
from versal.db.base import SessionLocal
from versal.db.models import GuestTicket, User
from versal.db.repo import apply_miss, get_or_create_user
from versal.services.security import format_deadline, is_free_entry_open, parse_ticket_token
from versal.texts import SCAN_PROMPT, VAL_EXPIRED, VAL_GUEST_NOTICE, VAL_INVALID, VAL_OK, VAL_USED

router = Router()

# Единый паттерн токена: и для фильтра сообщений, и для поиска в тексте
# (см. декоратор auto_detect_scan ниже).
_TOKEN_CORE = r"(\d+\.[0-9a-f]{16})"
_TOKEN_PATTERN = rf"(?:gl_)?{_TOKEN_CORE}"
GL_TOKEN_RE = re.compile(_TOKEN_PATTERN, re.IGNORECASE)


def _is_staff(telegram_id: int, role: str) -> bool:
    return role in ("staff", "admin") or telegram_id in settings.staff_ids or telegram_id in settings.admin_ids


async def validate_ticket_message(message: Message, token: str) -> None:
    """Общая точка валидации: и deep-link со сканирования, и команда /scan.
    Никогда не завершается молча: при любой ошибке отвечает и логирует."""
    import logging

    log = logging.getLogger(__name__)
    try:
        await _validate_ticket(message, token)
    except Exception:
        log.exception("Ошибка валидации квитка, токен=%r", token)
        try:
            await message.answer(VAL_INVALID)
        except Exception:
            log.exception("Не удалось даже ответить на валидацию")


async def _validate_ticket(message: Message, token: str) -> None:
    ticket_id = parse_ticket_token(token)
    if ticket_id is None:
        await message.answer(VAL_INVALID)
        return

    async with SessionLocal() as session:
        ticket = await session.get(GuestTicket, ticket_id)
        if ticket is None:
            await message.answer(VAL_INVALID)
            return

        # Кто сканирует: охрана/админ — гасим билет, гость — только информация
        mark_used = False
        if message.from_user:
            scanner = await get_or_create_user(
                session, message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            mark_used = _is_staff(message.from_user.id, scanner.role)

        if ticket.status == "used":
            used_at = ticket.used_at.strftime("%d.%m.%Y %H:%M") if ticket.used_at else "?"
            await message.answer(VAL_USED.format(used_at=used_at))
            return

        if not is_free_entry_open():
            if ticket.status == "active":
                # Квиток не использован: гасим как expired и считаем пропуском.
                # (Повторный скан того же квитка сюда не попадёт — статус уже expired.)
                ticket.status = "expired"
                owner = await session.get(User, ticket.user_id)
                if owner is not None:
                    apply_miss(owner)
                await session.commit()
            await message.answer(VAL_EXPIRED.format(deadline=format_deadline()))
            return

        # Квиток активен и время не вышло
        if mark_used:
            ticket.status = "used"
            ticket.used_at = datetime.now()
            user = await session.get(User, ticket.user_id)
            if user is not None:
                user.missed_tickets = 0  # гость пришёл — сбрасываем счётчик «мёртвых душ»
            await session.commit()
            await message.answer(VAL_OK.format(deadline=format_deadline()))
        else:
            await message.answer(VAL_OK.format(deadline=format_deadline()) + "\n" + VAL_GUEST_NOTICE)


@router.message(F.text.regexp(_TOKEN_PATTERN, search=True))
async def auto_detect_scan(message: Message, state: FSMContext) -> None:
    """Понимает deep-link без команды: просто вставь ссылку в чат —
    бот сам распознает токен и ответит статусом квитка."""
    # Не вмешиваемся в активные сценарии (бронь стола, админ-процессы)
    if await state.get_state() is not None:
        return
    match = GL_TOKEN_RE.search(message.text or "")
    if match:
        await validate_ticket_message(message, match.group(1))


@router.message(Command("scan"))
async def cmd_scan(message: Message) -> None:
    """Охрана может вставить токен вручную."""
    if not message.from_user:
        return
    async with SessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
    if not _is_staff(message.from_user.id, user.role):
        await message.answer("⛔️ Ця команда доступна тільки охороні та адміністратору.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer(SCAN_PROMPT)
        return

    # Принимаем и голый токен, и полную ссылку:
    #  3.47321609694f654f
    #  https://t.me/demo_nightclub_bot?start=gl_3.47321609694f654f
    raw = parts[1].strip()
    if "?start=" in raw:
        raw = raw.split("?start=")[1]
    raw = raw.split("/")[-1]
    if raw.startswith("gl_"):
        raw = raw[3:]
    await validate_ticket_message(message, raw)
