import asyncio
import sys

from versal.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit as exc:
        # Сообщения вида «Бот уже запущен (PID …)» должны быть видны пользователю
        if exc.code:
            print(exc.code, file=sys.stderr)
    except KeyboardInterrupt:
        pass
