from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "")
    return tuple(int(x) for x in raw.split(",") if x.strip().isdigit())


def _time(name: str, default: str) -> tuple[int, int]:
    raw = os.getenv(name, default)
    try:
        hour, minute = raw.split(":")
        return int(hour), int(minute)
    except ValueError:
        return 20, 0


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # Подпись QR: обязательный ключ, в проде задавать через env
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")

    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'versal.db').as_posix()}",
    )

    admin_ids: tuple[int, ...] = field(default_factory=lambda: _ids("ADMIN_IDS"))
    staff_ids: tuple[int, ...] = field(default_factory=lambda: _ids("STAFF_IDS"))

    guest_list_limit: int = field(default_factory=lambda: _int("GUEST_LIST_LIMIT", 100))
    guest_list_deadline: tuple[int, int] = field(default_factory=lambda: _time("GUEST_LIST_DEADLINE", "20:00"))

    # Количество неиспользованных билетов подряд до блокировки Guest List на 30 дней
    missed_tickets_to_block: int = 3
    block_days: int = 30

    data_dir: Path = BASE_DIR / "data"
    posters_dir: Path = BASE_DIR / "data" / "posters"
    hall_scheme_path: Path = BASE_DIR / "data" / "hall_scheme.png"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.posters_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
