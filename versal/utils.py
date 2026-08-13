from __future__ import annotations

import html


def esc(text: object) -> str:
    """Экранирует HTML-спецсимволы в пользовательском/админском тексте,
    чтобы некорректные <, >, & не ломали отправку сообщений с parse_mode=HTML."""
    return html.escape(str(text), quote=False)
