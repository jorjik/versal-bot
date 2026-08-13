from __future__ import annotations

import io
from pathlib import Path

import qrcode
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw

from versal.config import settings
from versal.services.security import telegram_start_param

_bot_username: str | None = None


async def get_bot_username(bot) -> str:
    """Кэширует username бота. Пустой результат не кэшируем —
    следующий вызов попробует ещё раз (иначе QR получит битую ссылку)."""
    global _bot_username
    if _bot_username:
        return _bot_username
    me = await bot.me()
    username = me.username or ""
    if username:
        _bot_username = username
    return username


def qr_deep_link(username: str, token: str) -> str:
    """Сканирование камерой открывает бота и запускает валидацию.

    Параметр start содержит только A-Z a-z 0-9 _ - — иначе Telegram
    отбрасывает payload, и по ссылке «ничего не происходит».
    """
    return f"https://t.me/{username}?start={telegram_start_param(token)}"


def make_qr_image(data: str) -> BufferedInputFile:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.getvalue(), filename="guest_list_qr.png")


def ensure_hall_scheme() -> Path:
    """Генерирует простую схему зала с зонами, если файла нет."""
    path = settings.hall_scheme_path
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (900, 560), "#14141f")
    draw = ImageDraw.Draw(img)

    zones = [
        (60, 60, 360, 260, "VIP-зона", "#7b2ff7"),
        (60, 290, 360, 490, "Караоке", "#f76b2f"),
        (390, 60, 690, 490, "Танцпол", "#2f8ef7"),
        (720, 60, 840, 260, "Бар", "#2fbf71"),
        (720, 290, 840, 490, "Сцена", "#e8e23a"),
    ]
    for x1, y1, x2, y2, label, color in zones:
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        draw.text((x1 + 20, y1 + 20), label, fill=color)

    draw.rectangle((60, 20, 200, 50), outline="#ffffff", width=2)
    draw.text((70, 26), "ВХІД", fill="#ffffff")

    img.save(path)
    return path
