from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from versal.db.base import SessionLocal
from versal.db.repo import CFG_MENU_FILE_ID, CFG_MENU_KIND, get_config
from versal.keyboards import back_to_menu_kb
from versal.texts import MENU_MISSING

router = Router()


@router.callback_query(F.data == "menu:menu")
async def show_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    async with SessionLocal() as session:
        file_id = await get_config(session, CFG_MENU_FILE_ID)
        kind = await get_config(session, CFG_MENU_KIND, "document")

    if not file_id:
        await callback.message.answer(MENU_MISSING, reply_markup=back_to_menu_kb())
        return

    caption = "🥂 Меню бару та кухні"
    if kind == "photo":
        await callback.message.answer_photo(
            photo=file_id, caption=caption, reply_markup=back_to_menu_kb()
        )
    else:
        await callback.message.answer_document(
            document=file_id, caption=caption, reply_markup=back_to_menu_kb()
        )
