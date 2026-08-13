from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from versal.config import settings
from versal.db.base import SessionLocal
from versal.db.repo import create_reservation, get_or_create_user
from versal.keyboards import back_to_menu_kb, reserve_manage_kb
from versal.services.assets import ensure_hall_scheme
from versal.services.security import reserve_limiter
from versal.utils import esc
from versal.texts import (
    NOT_REGISTERED,
    RESERVE_ADMIN_NOTIFY,
    RESERVE_ASK_GUESTS,
    RESERVE_ASK_WISHES,
    RESERVE_BAD_COUNT,
    RESERVE_DONE,
    RESERVE_START,
    RESERVE_TOO_FAST,
)

router = Router()


class ReserveStates(StatesGroup):
    date = State()
    guests = State()
    wishes = State()


async def _registered_user(message: Message) -> bool:
    async with SessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id)
        return bool(user.phone)


def reserve_admin_notify_text(reservation, user) -> str:
    """Текст уведомления админу о брони (ввод пользователя экранирован)."""
    text = RESERVE_ADMIN_NOTIFY.format(
        id=reservation.id,
        name=esc(user.first_name or "Гість"),
        username=esc(user.username or "-"),
        phone=esc(user.phone or "не вказано"),
        date_text=esc(reservation.date_text),
        guests=reservation.guests_count,
        wishes=esc(reservation.wishes or "без побажань"),
    )
    text += f"\n\n📝 Статус: <b>{esc(reservation.status)}</b>"
    return text


@router.callback_query(F.data == "menu:reserve")
async def reserve_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = callback.message

    if not await _registered_user(message):
        await message.answer(NOT_REGISTERED, reply_markup=back_to_menu_kb())
        return

    scheme = ensure_hall_scheme()
    await message.answer_photo(
        FSInputFile(scheme),
        caption=RESERVE_START,
        reply_markup=back_to_menu_kb(),
    )
    await state.set_state(ReserveStates.date)


@router.message(ReserveStates.date)
async def reserve_date(message: Message, state: FSMContext) -> None:
    # Обрезаем, чтобы не упереться в VARCHAR(64) на PostgreSQL
    await state.update_data(date_text=message.text.strip()[:64])
    await message.answer(RESERVE_ASK_GUESTS)
    await state.set_state(ReserveStates.guests)


@router.message(ReserveStates.guests)
async def reserve_guests(message: Message, state: FSMContext) -> None:
    try:
        count = int(message.text.strip())
    except ValueError:
        count = 0
    if not 1 <= count <= 50:
        await message.answer(RESERVE_BAD_COUNT)
        return
    await state.update_data(guests_count=count)
    await message.answer(RESERVE_ASK_WISHES)
    await state.set_state(ReserveStates.wishes)


@router.message(ReserveStates.wishes)
async def reserve_wishes(message: Message, state: FSMContext) -> None:
    if not reserve_limiter.allow(message.from_user.id):
        await message.answer(RESERVE_TOO_FAST, reply_markup=back_to_menu_kb())
        await state.clear()
        return

    data = await state.get_data()
    wishes = message.text.strip()
    if wishes == "-":
        wishes = "без побажань"

    async with SessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        reservation = await create_reservation(
            session,
            user,
            date_text=data.get("date_text", "?"),
            guests_count=int(data.get("guests_count", 1)),
            wishes=wishes,
        )

    phone = user.phone or "не вказано"
    await message.answer(RESERVE_DONE.format(phone=esc(phone)), reply_markup=back_to_menu_kb())

    # Уведомляем администраторов (экранируем пользовательский ввод)
    notify = reserve_admin_notify_text(reservation, user)
    kb = reserve_manage_kb(reservation.id)
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, notify, reply_markup=kb)
        except Exception:
            pass  # админ мог заблокировать бота — не роняем поток

    await state.clear()


@router.message(Command("reserve"))
async def cmd_reserve(message: Message, state: FSMContext) -> None:
    if not await _registered_user(message):
        await message.answer(NOT_REGISTERED)
        return
    scheme = ensure_hall_scheme()
    await message.answer_photo(FSInputFile(scheme), caption=RESERVE_START)
    await state.set_state(ReserveStates.date)
