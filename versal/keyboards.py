from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

CONTACT_REQUEST = "📱 Поділитись номером"


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONTACT_REQUEST, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Guest List", callback_data="menu:guest_list")],
            [InlineKeyboardButton(text="📅 Афіша подій", callback_data="menu:afisha")],
            [InlineKeyboardButton(text="🥂 Меню", callback_data="menu:menu")],
            [InlineKeyboardButton(text="🛋 Бронювання столів", callback_data="menu:reserve")],
        ]
    )


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Головне меню", callback_data="menu:main")]]
    )


def guest_list_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Записатись", callback_data="gl:confirm")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="gl:cancel")],
        ]
    )


def reserve_manage_kb(reservation_id: int) -> InlineKeyboardMarkup:
    """Кнопки для админа в уведомлении о новой брони."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Деталі броні",
                    callback_data=f"admin:reserve_info:{reservation_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Підтвердити",
                    callback_data=f"admin:reserve_set:{reservation_id}:confirmed",
                ),
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=f"admin:reserve_set:{reservation_id}:cancelled",
                ),
            ],
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="🎫 Ліміт Guest List", callback_data="admin:limit")],
            [InlineKeyboardButton(text="🚦 Відкрити/Закрити запис", callback_data="admin:toggle_gl")],
            [InlineKeyboardButton(text="📅 Додати подію", callback_data="admin:add_event")],
            [InlineKeyboardButton(text="🗑 Видалити подію", callback_data="admin:del_event")],
            [InlineKeyboardButton(text="🥂 Оновити меню", callback_data="admin:set_menu")],
            [InlineKeyboardButton(text="📣 Розсилка", callback_data="admin:mail")],
            [InlineKeyboardButton(text="🧹 Мертві душі (sweep)", callback_data="admin:sweep")],
            [InlineKeyboardButton(text="🚫 Заблоковані", callback_data="admin:blocked")],
            [InlineKeyboardButton(text="🧾 Останні броні", callback_data="admin:reservations")],
        ]
    )
