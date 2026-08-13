from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from versal.db.base import SessionLocal
from versal.db.repo import get_or_create_user, get_user
from versal.handlers.validation import validate_ticket_message
from versal.keyboards import CONTACT_REQUEST, contact_kb, main_menu_kb, remove_kb
from versal.services.security import format_deadline
from versal.texts import (
    MAIN_MENU_TITLE,
    NOT_REGISTERED,
    REGISTERED,
    WELCOME,
    WELCOME_BACK,
)
from versal.utils import esc

import logging

router = Router()
log = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    # Deep-link от QR-кода гостя: t.me/bot?start=gl_<token>
    payload = message.text.split(" ", 1)[1] if (message.text and " " in message.text) else ""
    if payload.startswith("gl_"):
        log.info("Валидация по deep-link от %s: %s", message.from_user.id, payload)
        await validate_ticket_message(message, payload[3:])
        return

    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

    if user.phone:
        name = esc(user.first_name or "друг")
        await message.answer(WELCOME_BACK.format(name=name), reply_markup=main_menu_kb())
    else:
        await message.answer(WELCOME.format(deadline=format_deadline()), reply_markup=contact_kb())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    async with SessionLocal() as session:
        user = await get_user(session, message.from_user.id)
    if not user or not user.phone:
        await message.answer(NOT_REGISTERED, reply_markup=contact_kb())
        return
    await message.answer(MAIN_MENU_TITLE, reply_markup=main_menu_kb())


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    contact = message.contact
    if contact is None:
        return
    phone = contact.phone_number
    if message.from_user and message.from_user.id != contact.user_id:
        phone = None  # прислали чужой контакт — не сохраняем номер

    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            phone=phone,
        )

    if user.phone:
        await message.answer(REGISTERED, reply_markup=remove_kb())
        await message.answer(MAIN_MENU_TITLE, reply_markup=main_menu_kb())
    else:
        await message.answer(WELCOME.format(deadline=format_deadline()), reply_markup=contact_kb())


@router.message(F.text == CONTACT_REQUEST)
async def on_contact_button_text(message: Message) -> None:
    """Если кнопка request_contact не сработала — подсказываем."""
    await message.answer("Натисніть кнопку нижче 👇", reply_markup=contact_kb())


@router.callback_query(F.data == "menu:main")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(MAIN_MENU_TITLE, reply_markup=main_menu_kb())
