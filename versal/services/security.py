from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, time as dtime

from versal.config import settings


def _sign(payload: str) -> str:
    return hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def make_ticket_token(ticket_id: int) -> str:
    """Подписанный токен: <id>.<hmac>. В QR кладётся deep-link с этим токеном."""
    payload = str(ticket_id)
    return f"{payload}.{_sign(payload)}"


def parse_ticket_token(token: str) -> int | None:
    """Возвращает ticket_id, если подпись валидна, иначе None."""
    try:
        payload, signature = token.split(".", 1)
        if hmac.compare_digest(_sign(payload), signature):
            return int(payload)
    except (ValueError, TypeError):
        return None
    return None


def guest_list_deadline_time() -> dtime:
    hour, minute = settings.guest_list_deadline
    return dtime(hour, minute)


def is_free_entry_open(now: datetime | None = None) -> bool:
    """Бесплатный вход действует до 20:00 включительно (на 20:01 уже закрыт)."""
    now = now or datetime.now()
    return now.time() <= guest_list_deadline_time()


def format_deadline() -> str:
    hour, minute = settings.guest_list_deadline
    return f"{hour:02d}:{minute:02d}"


class RateLimiter:
    """Простой in-memory ограничитель частоты запросов (анти-накрутка)."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last: dict[int, float] = {}

    def allow(self, key: int, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        last = self._last.get(key)
        if last is None or now - last >= self.min_interval:
            self._last[key] = now
            return True
        return False


# Генерация QR не чаще раза в минуту на пользователя; заявки на стол — раз в 30 сек
guest_list_limiter = RateLimiter(60.0)
reserve_limiter = RateLimiter(30.0)
