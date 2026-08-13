from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, ErrorEvent

from versal.config import settings
from versal.db.base import SessionLocal, init_db
from versal.db.repo import ensure_defaults
from versal.handlers import admin, afisha, guest_list, menu, reservations, start, validation
from versal.services.assets import ensure_hall_scheme
from versal.singleton import acquire_lock, release_lock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def _cmd(name: str, desc: str) -> BotCommand:
    return BotCommand(command=name, description=desc)


GUEST_COMMANDS = [
    _cmd("start", "Головне меню"),
    _cmd("menu", "Головне меню"),
    _cmd("reserve", "Бронювання столів"),
    _cmd("cancel", "Скасувати дію"),
]

STAFF_COMMANDS = GUEST_COMMANDS + [_cmd("scan", "Валідація QR (охрана)")]

ADMIN_COMMANDS = STAFF_COMMANDS + [
    _cmd("admin", "Панель адміністратора"),
    _cmd("set_limit", "Ліміт Guest List"),
    _cmd("close_gl", "Закрити запис"),
    _cmd("open_gl", "Відкрити запис"),
    _cmd("del_event", "Видалити подію"),
    _cmd("unblock", "Розблокувати користувача"),
    _cmd("reserve_info", "Деталі броні"),
    _cmd("reserve_set", "Статус броні"),
]


async def on_error(event: ErrorEvent) -> None:
    """Глобальный обработчик ошибок: любой сбой в хендлере логируется,
    а не проглатывается молча."""
    log.error("Ошибка в обработчике: %s", event.exception, exc_info=event.exception)


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(GUEST_COMMANDS, scope=BotCommandScopeDefault())
    for uid in settings.staff_ids:
        try:
            await bot.set_my_commands(STAFF_COMMANDS, scope=BotCommandScopeChat(chat_id=uid))
        except Exception:
            log.warning("Не удалось задать команды для охраны %s", uid)
    for uid in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=uid))
        except Exception:
            log.warning("Не удалось задать команды для админа %s", uid)


async def main() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")

    settings.ensure_dirs()

    # Защита от двух экземпляров: второй процесс не запустится,
    # иначе Telegram раздаёт апдейты между ними и часть сообщений теряется.
    lock_path = settings.data_dir / "bot.pid"
    if not acquire_lock(lock_path):
        holder = ""
        try:
            holder = f" (PID {lock_path.read_text().strip()})"
        except Exception:
            pass
        raise SystemExit(
            f"Бот уже запущен{holder} — см. data/bot.pid.\n"
            "Закройте старый процесс и запустите снова."
        )

    try:
        if settings.secret_key == "dev-secret-change-me":
            log.warning("SECRET_KEY не задан! Используется дефолтный ключ — в проде замените его.")
        await init_db()
        async with SessionLocal() as session:
            await ensure_defaults(session)
        ensure_hall_scheme()

        bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher(storage=MemoryStorage())
        dp.errors.register(on_error)

        dp.include_routers(
            start.router,
            guest_list.router,
            afisha.router,
            menu.router,
            reservations.router,
            admin.router,
            validation.router,  # последним: авто-распознавание ссылок не мешает FSM-процессам
        )

        await set_commands(bot)
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.me()
        log.info("Бот «Версаль» запущен: @%s (id=%s)", me.username, me.id)
        await dp.start_polling(bot)
    finally:
        release_lock(lock_path)


if __name__ == "__main__":
    import asyncio
    import sys

    try:
        asyncio.run(main())
    except SystemExit as exc:
        if exc.code:
            print(exc.code, file=sys.stderr)
    except KeyboardInterrupt:
        pass
