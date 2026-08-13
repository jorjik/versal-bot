from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from versal.config import settings
from versal.db.base import SessionLocal
from versal.db.models import Event, GuestTicket, TableReservation, User
from versal.db.repo import (
    CFG_GUEST_LIST_LIMIT,
    CFG_GUEST_LIST_OPEN,
    CFG_MENU_FILE_ID,
    CFG_MENU_KIND,
    active_tickets_today,
    create_event,
    get_config,
    get_event,
    get_guest_list_limit,
    is_guest_list_open,
    list_active_events,
    list_blocked_users,
    list_reservations,
    set_config,
    sweep_missed_tickets,
    unblock_user,
)
from versal.handlers.reservations import reserve_admin_notify_text
from versal.keyboards import admin_panel_kb, back_to_menu_kb, reserve_manage_kb
from versal.services.security import format_deadline
from versal.texts import ADMIN_ONLY, ADMIN_PANEL, CANCEL_ANY, DONE, NOT_FOUND
from versal.utils import esc

router = Router()

MISSED_TO_BLOCK = settings.missed_tickets_to_block


# ---------------------------------------------------------------------------
# Гварды и помощники
# ---------------------------------------------------------------------------
def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


class AdminStates(StatesGroup):
    add_event_title = State()
    add_event_date = State()
    add_event_price = State()
    add_event_desc = State()
    add_event_poster = State()
    mail_text = State()
    mail_photo = State()
    mail_audience = State()
    set_menu = State()


def _admin_only(message: Message) -> bool:
    if message.from_user and _is_admin(message.from_user.id):
        return True
    return False


# ---------------------------------------------------------------------------
# Панель
# ---------------------------------------------------------------------------
@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _admin_only(message):
        await message.answer(ADMIN_ONLY)
        return
    await message.answer(ADMIN_PANEL, reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        await callback.message.answer(ADMIN_ONLY)
        return

    from sqlalchemy import func, select

    async with SessionLocal() as session:
        users_total = await session.scalar(select(func.count()).select_from(User)) or 0
        events_total = await session.scalar(select(func.count()).select_from(Event)) or 0
        tickets_today = await active_tickets_today(session)
        used_total = await session.scalar(
            select(func.count()).select_from(GuestTicket).where(GuestTicket.status == "used")
        ) or 0
        reservations_total = await session.scalar(
            select(func.count()).select_from(TableReservation)
        ) or 0
        blocked_total = await session.scalar(
            select(func.count()).select_from(User).where(User.is_blocked_guest_list == True)
        ) or 0
        limit = await get_guest_list_limit(session)
        open_ = await is_guest_list_open(session)

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Користувачів у базі: <b>{users_total}</b>\n"
        f"📅 Подій: <b>{events_total}</b>\n\n"
        f"🎫 Активних квитків сьогодні: <b>{tickets_today}</b> / {limit}\n"
        f"✅ Використано квитків (всього): <b>{used_total}</b>\n"
        f"🛋 Броней: <b>{reservations_total}</b>\n"
        f"🚫 Заблокованих: <b>{blocked_total}</b>\n\n"
        f"Запис Guest List: <b>{'відкрито' if open_ else 'закрито'}</b>\n"
        f"⏰ Дедлайн: {format_deadline()}"
    )
    await callback.message.answer(text, reply_markup=back_to_menu_kb())


@router.callback_query(F.data == "admin:limit")
async def admin_limit(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        limit = await get_guest_list_limit(session)
    await callback.message.answer(
        f"🎫 Поточний ліміт Guest List: <b>{limit}</b>.\n\n"
        f"Встановити новий: <code>/set_limit 150</code>",
        reply_markup=back_to_menu_kb(),
    )


@router.message(Command("set_limit"))
async def admin_set_limit(message: Message) -> None:
    if not _admin_only(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/set_limit 150</code>")
        return
    limit = int(parts[1])
    if not 1 <= limit <= 10_000:
        await message.answer("Ліміт має бути від 1 до 10000.")
        return
    async with SessionLocal() as session:
        await set_config(session, CFG_GUEST_LIST_LIMIT, str(limit))
    await message.answer(f"✅ Ліміт Guest List: <b>{limit}</b> місць.")


@router.callback_query(F.data == "admin:toggle_gl")
async def admin_toggle_gl(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        open_ = await is_guest_list_open(session)
        await set_config(session, CFG_GUEST_LIST_OPEN, "0" if open_ else "1")
    await callback.message.answer(
        f"🚦 Запис Guest List тепер: <b>{'закрито' if open_ else 'відкрито'}</b>."
    )


@router.message(Command("close_gl"))
async def admin_close_gl(message: Message) -> None:
    if not _admin_only(message):
        return
    async with SessionLocal() as session:
        await set_config(session, CFG_GUEST_LIST_OPEN, "0")
    await message.answer("🚦 Запис Guest List <b>закрито</b>.")


@router.message(Command("open_gl"))
async def admin_open_gl(message: Message) -> None:
    if not _admin_only(message):
        return
    async with SessionLocal() as session:
        await set_config(session, CFG_GUEST_LIST_OPEN, "1")
    await message.answer("🚦 Запис Guest List <b>відкрито</b>.")


# ---------------------------------------------------------------------------
# События (афиша)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "admin:add_event")
async def admin_add_event(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    await callback.message.answer("📅 Назва події:")
    await state.set_state(AdminStates.add_event_title)


@router.message(AdminStates.add_event_title)
async def event_title(message: Message, state: FSMContext) -> None:
    # Обрезаем под VARCHAR(255) — иначе PostgreSQL уронит запрос
    await state.update_data(title=message.text.strip()[:255])
    await message.answer("🗓 Дата і час (формат <i>DD.MM.YYYY HH:MM</i> або будь-який текст):")
    await state.set_state(AdminStates.add_event_date)


@router.message(AdminStates.add_event_date)
async def event_date(message: Message, state: FSMContext) -> None:
    await state.update_data(date_text=message.text.strip())
    await message.answer("💰 Вартість входу (або «-»):")
    await state.set_state(AdminStates.add_event_price)


@router.message(AdminStates.add_event_price)
async def event_price(message: Message, state: FSMContext) -> None:
    await state.update_data(price=message.text.strip()[:128])
    await message.answer("📝 Опис події (або «-»):")
    await state.set_state(AdminStates.add_event_desc)


@router.message(AdminStates.add_event_desc)
async def event_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await message.answer("🖼 Надішліть постер (фото) або «-», щоб пропустити:")
    await state.set_state(AdminStates.add_event_poster)


@router.message(AdminStates.add_event_poster)
async def event_poster(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    poster_path = None
    if message.photo:
        try:
            poster_path = await _save_photo(message)
        except Exception:
            poster_path = None

    starts_at = None
    date_text = data.get("date_text", "")
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m %H:%M", "%d.%m.%Y", "%H:%M"):
        try:
            starts_at = datetime.strptime(date_text, fmt)
            break
        except ValueError:
            continue
    if starts_at is not None and starts_at.year == 1900:
        starts_at = starts_at.replace(year=datetime.now().year)

    async with SessionLocal() as session:
        event = await create_event(
            session,
            title=data.get("title", "?"),
            starts_at=starts_at,
            price=None if data.get("price") in (None, "-") else data.get("price"),
            description=None if data.get("description") in (None, "-") else data.get("description"),
            poster_path=poster_path,
        )

    await message.answer(
        f"✅ Подію додано (#{event.id}): <b>{event.title}</b>",
        reply_markup=back_to_menu_kb(),
    )
    await state.clear()


async def _delete_event_by_id(event_id: int) -> bool:
    """Удаляет подію и файл постера с диска; True, если подія была."""
    async with SessionLocal() as session:
        event = await get_event(session, event_id)
        if event is None:
            return False
        poster = Path(event.poster_path) if event.poster_path else None
        await session.delete(event)
        await session.commit()
    # Убираем файл постера с диска, чтобы мусор не копился
    if poster and poster.exists():
        try:
            poster.unlink()
        except OSError:
            pass
    return True


@router.callback_query(F.data == "admin:del_event")
async def admin_list_events(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        events = await list_active_events(session, limit=20)
    if not events:
        await callback.message.answer("Подій немає.", reply_markup=back_to_menu_kb())
        return
    lines = ["🗑 <b>Події</b> (натисніть кнопку, щоб видалити):\n"]
    for event in events:
        date_part = event.starts_at.strftime("%d.%m %H:%M") if event.starts_at else "без дати"
        lines.append(f"#{event.id} • {date_part} • {esc(event.title)}")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🗑 #{event.id} • {event.title[:40]}",
                    callback_data=f"admin:del_event:{event.id}",
                )
            ]
            for event in events
        ]
        + [[InlineKeyboardButton(text="⬅️ Головне меню", callback_data="menu:main")]]
    )
    await callback.message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("admin:del_event:"))
async def admin_del_event_confirm(callback: CallbackQuery) -> None:
    """Кнопка «🗑 #id» — запрашиваем подтверждение перед удалением."""
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    rid = callback.data.split(":", 2)[2]
    if not rid.isdigit():
        return
    async with SessionLocal() as session:
        event = await get_event(session, int(rid))
    if event is None:
        await callback.message.answer(NOT_FOUND)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Видалити", callback_data=f"admin:del_event_yes:{rid}"
                ),
                InlineKeyboardButton(text="❌ Ні", callback_data="admin:del_event_no"),
            ]
        ]
    )
    await callback.message.answer(
        f"Видалити подію #{event.id} «{esc(event.title)}»?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("admin:del_event_yes:"))
async def admin_del_event_do(callback: CallbackQuery) -> None:
    """Подтверждённое удаление."""
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    rid = callback.data.split(":", 2)[2]
    if not rid.isdigit():
        return
    if await _delete_event_by_id(int(rid)):
        await callback.message.edit_text("✅ Подію видалено.")
    else:
        await callback.message.edit_text(NOT_FOUND)


@router.callback_query(F.data == "admin:del_event_no")
async def admin_del_event_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Скасовано")


@router.message(Command("del_event"))
async def admin_del_event(message: Message) -> None:
    if not _admin_only(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/del_event 3</code>")
        return
    await message.answer(DONE if await _delete_event_by_id(int(parts[1])) else NOT_FOUND)


# ---------------------------------------------------------------------------
# Меню
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "admin:set_menu")
async def admin_set_menu_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    await callback.message.answer(
        "🥂 Надішліть файл меню (PDF/фото). Воно одразу з'явиться у гостей."
    )
    await state.set_state(AdminStates.set_menu)


@router.message(AdminStates.set_menu)
async def admin_set_menu(message: Message, state: FSMContext) -> None:
    if message.document:
        file_id = message.document.file_id
        kind = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        kind = "photo"
    else:
        await message.answer("Надішліть файл або фото меню.")
        return
    async with SessionLocal() as session:
        await set_config(session, CFG_MENU_FILE_ID, file_id)
        await set_config(session, CFG_MENU_KIND, kind)
    await message.answer("✅ Меню оновлено.", reply_markup=back_to_menu_kb())
    await state.clear()


# ---------------------------------------------------------------------------
# Рассылка
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "admin:mail")
async def admin_mail_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    await callback.message.answer("📣 Текст розсилки:")
    await state.set_state(AdminStates.mail_text)


@router.message(AdminStates.mail_text)
async def mail_text(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.text)
    await message.answer("🖼 Фото до розсилки — або «-», щоб пропустити:")
    await state.set_state(AdminStates.mail_photo)


@router.message(AdminStates.mail_photo)
async def mail_photo(message: Message, state: FSMContext) -> None:
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer(
        "👥 Кому надіслати?\n\n"
        "1 — всім користувачам\n"
        "2 — тільки тим, хто хоч раз користувався Guest List"
    )
    await state.set_state(AdminStates.mail_audience)


@router.message(AdminStates.mail_audience)
async def mail_audience(message: Message, state: FSMContext) -> None:
    from sqlalchemy import select

    choice = message.text.strip()
    if choice not in ("1", "2"):
        await message.answer("Введіть <b>1</b> (всі) або <b>2</b> (користувачі Guest List).")
        return

    data = await state.get_data()
    mail_text = esc(data.get("text", "") or "")  # текст рассылки — тоже HTML, экранируем
    photo_id = data.get("photo_id")

    async with SessionLocal() as session:
        if choice == "2":
            users = list(
                (await session.execute(select(User).join(GuestTicket).distinct())).scalars().all()
            )
        else:
            users = list((await session.execute(select(User))).scalars().all())

    sent, failed = 0, 0
    for user in users:
        if await _mail_send(message.bot, user.telegram_id, mail_text, photo_id):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(
        f"✅ Розсилку завершено.\n"
        f"Надіслано: <b>{sent}</b>, помилок: <b>{failed}</b>",
        reply_markup=back_to_menu_kb(),
    )
    await state.clear()


async def _mail_send(bot, chat_id: int, text: str, photo_id: str | None) -> bool:
    """Отправляет сообщение; при 429 ждёт retry_after и пробует ещё раз."""
    async def _send() -> None:
        if photo_id:
            await bot.send_photo(chat_id, photo=photo_id, caption=text)
        else:
            await bot.send_message(chat_id, text)

    try:
        await _send()
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 1)
        try:
            await _send()
            return True
        except TelegramAPIError:
            return False
    except TelegramAPIError:
        return False


# ---------------------------------------------------------------------------
# Мёртвые души / блокировки / брони
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "admin:sweep")
async def admin_sweep(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        blocked = await sweep_missed_tickets(session)
    await callback.message.answer(
        f"🧹 Перевірено. Заблоковано нових: <b>{blocked}</b>.\n"
        f"Правило: {MISSED_TO_BLOCK} невикористаних квитків поспіль → блок на {settings.block_days} днів."
    )


@router.callback_query(F.data == "admin:blocked")
async def admin_blocked(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        users = await list_blocked_users(session)
    if not users:
        await callback.message.answer("🚫 Заблокованих немає.", reply_markup=back_to_menu_kb())
        return
    lines = ["🚫 <b>Заблоковані</b> (розблокувати: <code>/unblock 123456789</code>):\n"]
    for user in users:
        until = user.blocked_until.strftime("%d.%m.%Y %H:%M") if user.blocked_until else "?"
        name = esc(user.first_name or user.username or "?")
        lines.append(f"• <code>{user.telegram_id}</code> {name} — до {until} ({user.missed_tickets} пропусків)")
    await callback.message.answer("\n".join(lines), reply_markup=back_to_menu_kb())


@router.message(Command("unblock"))
async def admin_unblock(message: Message) -> None:
    if not _admin_only(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/unblock 123456789</code>")
        return
    async with SessionLocal() as session:
        user = await unblock_user(session, int(parts[1]))
    await message.answer(DONE if user else NOT_FOUND)


@router.callback_query(F.data == "admin:reservations")
async def admin_reservations(callback: CallbackQuery) -> None:
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    async with SessionLocal() as session:
        reservations = await list_reservations(session, limit=10)
    if not reservations:
        await callback.message.answer("🧾 Броней поки немає.", reply_markup=back_to_menu_kb())
        return
    lines = ["🧾 <b>Останні броні</b>:\n"]
    for r in reservations:
        user = await session.get(User, r.user_id)
        phone = user.phone if user else "?"
        name = (user.first_name if user else None) or "?"
        lines.append(
            f"#{r.id} • {r.created_at.strftime('%d.%m %H:%M')} • {r.date_text} • "
            f"{r.guests_count} ос. • {name} ({phone})"
        )
    await callback.message.answer("\n".join(lines), reply_markup=back_to_menu_kb())


@router.message(Command("reserve_set"))
async def admin_reserve_set(message: Message) -> None:
    """Меняет статус брони: /reserve_set 5 confirmed (new/confirmed/cancelled)."""
    if not _admin_only(message):
        return
    parts = message.text.split()
    if len(parts) < 3 or not parts[1].isdigit() or parts[2] not in ("new", "confirmed", "cancelled"):
        await message.answer("Формат: <code>/reserve_set 5 confirmed</code> (new/confirmed/cancelled)")
        return
    async with SessionLocal() as session:
        reservation = await session.get(TableReservation, int(parts[1]))
        if reservation is None:
            await message.answer(NOT_FOUND)
            return
        reservation.status = parts[2]
        await session.commit()
    await message.answer(f"✅ Бронь #{parts[1]}: <b>{parts[2]}</b>")


async def _show_reserve_details(answer, rid: int) -> bool:
    """Отправляет карточку брони; answer — callable, принимающий текст."""
    async with SessionLocal() as session:
        reservation = await session.get(TableReservation, rid)
        if reservation is None:
            await answer(NOT_FOUND)
            return False
        user = await session.get(User, reservation.user_id)
        await answer(
            f"🛋 <b>Бронь #{reservation.id}</b>\n"
            f"👤 {esc(user.first_name or '?')} (@{esc(user.username or '-')})\n"
            f"📞 {esc(user.phone or 'не вказано')}\n"
            f"📅 {esc(reservation.date_text)}\n"
            f"👥 {reservation.guests_count} ос.\n"
            f"💬 {esc(reservation.wishes or '-')}\n"
            f"📝 Статус: {esc(reservation.status)}\n"
            f"🕒 Створено: {reservation.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
    return True


@router.message(Command("reserve_info"))
async def admin_reserve_info(message: Message) -> None:
    if not _admin_only(message):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return
    await _show_reserve_details(message.answer, int(parts[1]))


@router.callback_query(F.data.startswith("admin:reserve_info:"))
async def admin_reserve_info_cb(callback: CallbackQuery) -> None:
    """Кнопка «Деталі броні» в уведомлении."""
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    rid = callback.data.split(":", 2)[2]
    if not rid.isdigit():
        return
    await _show_reserve_details(callback.message.answer, int(rid))


@router.callback_query(F.data.startswith("admin:reserve_set:"))
async def admin_reserve_set_cb(callback: CallbackQuery) -> None:
    """Кнопки «Підтвердити» / «Скасувати» в уведомлении."""
    await callback.answer()
    if not _is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in ("new", "confirmed", "cancelled"):
        return
    rid, status = int(parts[2]), parts[3]

    async with SessionLocal() as session:
        reservation = await session.get(TableReservation, rid)
        if reservation is None:
            await callback.message.answer(NOT_FOUND)
            return
        reservation.status = status
        await session.commit()
        user = await session.get(User, reservation.user_id)
        # Обновляем само уведомление прямо в чате: новый статус + кнопки
        try:
            await callback.message.edit_text(
                reserve_admin_notify_text(reservation, user),
                reply_markup=reserve_manage_kb(rid),
            )
        except TelegramBadRequest:
            pass  # сообщение могли удалить или уже изменить
        await callback.message.answer(f"✅ Бронь #{rid}: <b>{status}</b>")


# ---------------------------------------------------------------------------
# Отмена FSM
# ---------------------------------------------------------------------------
@router.message(Command("cancel"))
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer(CANCEL_ANY)


async def _save_photo(message: Message) -> str:
    """Скачивает последнее фото сообщения в data/posters и возвращает путь."""
    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)
    suffix = Path(file.file_path or "").suffix or ".jpg"
    dest = settings.posters_dir / f"event_{uuid.uuid4().hex}{suffix}"
    await message.bot.download_file(file.file_path, destination=dest)
    return str(dest)
