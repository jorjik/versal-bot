from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, time as dtime

from versal.config import settings


def _sign(payload: str) -> str:
    return hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


# Telegram ?start= допускает только A-Z a-z 0-9 _ - (точка запрещена и
# молча отбрасывается — бот вообще не получает /start). Поэтому в токене
# разделитель — '_'. Старые квитки с '.' по-прежнему распознаём.
_TOKEN_SEP = "_"


def make_ticket_token(ticket_id: int) -> str:
    """Подписанный токен: <id>_<hmac>. В QR кладётся deep-link с этим токеном."""
    payload = str(ticket_id)
    return f"{payload}{_TOKEN_SEP}{_sign(payload)}"


def parse_ticket_token(token: str) -> int | None:
    """Возвращает ticket_id, если подпись валидна, иначе None.

    Принимает и новый формат ``id_hmac``, и старый ``id.hmac``.
    """
    token = (token or "").strip()
    sep = _TOKEN_SEP if _TOKEN_SEP in token else "." if "." in token else None
    if sep is None:
        return None
    try:
        payload, signature = token.split(sep, 1)
        if hmac.compare_digest(_sign(payload), signature):
            return int(payload)
    except (ValueError, TypeError):
        return None
    return None


def telegram_start_param(token: str) -> str:
    """Payload для t.me/bot?start=… — без точек и прочих запрещённых символов."""
    return f"gl_{token.replace('.', _TOKEN_SEP)}"


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
