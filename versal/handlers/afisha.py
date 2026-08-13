from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile

from versal.db.base import SessionLocal
from versal.db.repo import list_active_events
from versal.keyboards import back_to_menu_kb
from versal.texts import AFISHA_EMPTY, AFISHA_EVENT
from versal.utils import esc

router = Router()


@router.callback_query(F.data == "menu:afisha")
async def afisha(callback: CallbackQuery) -> None:
    await callback.answer()
    message = callback.message

    async with SessionLocal() as session:
        events = await list_active_events(session)

    if not events:
        await message.answer(AFISHA_EMPTY, reply_markup=back_to_menu_kb())
        return

    for event in events:
        date_part = f"🗓 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n" if event.starts_at else ""
        price_part = f"💰 {event.price}\n" if event.price else ""
        desc_part = f"\n{event.description}" if event.description else ""
        text = AFISHA_EVENT.format(
            title=esc(event.title),
            date_part=date_part,
            price_part=esc(price_part),
            description=esc(desc_part),
        )

        poster = Path(event.poster_path) if event.poster_path else None
        if poster and poster.exists():
            await message.answer_photo(
                FSInputFile(poster),
                caption=text,
                reply_markup=back_to_menu_kb(),
            )
        else:
            await message.answer(text, reply_markup=back_to_menu_kb())
