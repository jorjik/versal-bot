from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from versal.db.base import SessionLocal
from versal.db.models import GuestTicket, User
from versal.db.repo import (
    active_ticket_for_user_today,
    active_tickets_today,
    get_guest_list_limit,
    get_or_create_user,
    is_blocked_for_guest_list,
    is_guest_list_open,
    sweep_missed_tickets,
    try_create_ticket_atomic,
)
from versal.keyboards import back_to_menu_kb, guest_list_confirm_kb
from versal.services.assets import get_bot_username, make_qr_image, qr_deep_link
from versal.services.security import (
    format_deadline,
    guest_list_limiter,
    is_free_entry_open,
)
from versal.texts import (
    GL_BLOCKED,
    GL_CLOSED,
    GL_CONFIRM_PROMPT,
    GL_LIMIT_REACHED,
    GL_SLOW_DOWN,
    GL_SUCCESS,
    GL_TOO_LATE,
    NOT_REGISTERED,
)

router = Router()


async def _prechecks(session, user: User, message: Message) -> bool:
    """Общие проверки перед записью. Отвечает пользователю и возвращает False,
    если запись невозможна; True — можно продолжать."""
    if not user.phone:
        await message.answer(NOT_REGISTERED)
        return False
    if is_blocked_for_guest_list(user):
        until = user.blocked_until.strftime("%d.%m.%Y %H:%M") if user.blocked_until else "?"
        await message.answer(GL_BLOCKED.format(until=until, misses=user.missed_tickets), reply_markup=back_to_menu_kb())
        return False
    if not is_free_entry_open():
        await message.answer(GL_TOO_LATE.format(deadline=format_deadline()), reply_markup=back_to_menu_kb())
        return False
    if not await is_guest_list_open(session):
        await message.answer(GL_CLOSED, reply_markup=back_to_menu_kb())
        return False
    return True


@router.callback_query(F.data == "menu:guest_list")
async def guest_list_start(callback: CallbackQuery) -> None:
    await callback.answer()
    message = callback.message

    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        # Ленивая чистка «мёртвых душ» перед каждой попыткой записи
        await sweep_missed_tickets(session)
        if not await _prechecks(session, user, message):
            return

        existing = await active_ticket_for_user_today(session, user)
        if existing is not None:
            await send_ticket(message, existing)
            return

        # Информационная проверка лимита: финальная — атомарная, при подтверждении
        limit = await get_guest_list_limit(session)
        if await active_tickets_today(session) >= limit:
            await message.answer(GL_LIMIT_REACHED, reply_markup=back_to_menu_kb())
            return

    await message.answer(GL_CONFIRM_PROMPT, reply_markup=guest_list_confirm_kb())


@router.callback_query(F.data == "gl:confirm")
async def guest_list_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    message = callback.message

    if not guest_list_limiter.allow(callback.from_user.id):
        await message.answer(GL_SLOW_DOWN, reply_markup=back_to_menu_kb())
        return

    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await sweep_missed_tickets(session)
        if not await _prechecks(session, user, message):
            return

        existing = await active_ticket_for_user_today(session, user)
        if existing is not None:
            await send_ticket(message, existing)
            return

        # Проверка лимита + вставка в одной транзакции (FOR UPDATE на Postgres)
        ticket = await try_create_ticket_atomic(session, user)
        if ticket is None:
            await message.answer(GL_LIMIT_REACHED, reply_markup=back_to_menu_kb())
            return

    await send_ticket(message, ticket)


@router.callback_query(F.data == "gl:cancel")
async def guest_list_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("❌ Запис скасовано.", reply_markup=back_to_menu_kb())


async def send_ticket(message: Message, ticket: GuestTicket) -> None:
    """Отправляет QR с deep-link и текст о правилах."""
    username = await get_bot_username(message.bot)
    link = qr_deep_link(username, ticket.token)
    photo = make_qr_image(link)
    await message.answer_photo(
        photo,
        caption=GL_SUCCESS.format(deadline=format_deadline()),
        reply_markup=back_to_menu_kb(),
    )
