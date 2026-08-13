# 🎉 Telegram-бот нічного клубу «Версаль»

Реалізація технічного завдання (див. `plan.txt`) на **Python + aiogram 3.x**.

## Ролі

| Роль | Можливості |
|---|---|
| **Гість** | Guest List з одноразовим QR, афіша, меню, бронювання столів |
| **Охорона/Хостес** | Валідація QR-квитків (скане камерою або `/scan`) |
| **Адміністратор** | Ліміти, закриття запису, події, меню, розсилки, статистика, блокування |

## Що реалізовано з ТЗ

- ✅ Guest List: безкоштовний вхід до 20:00, ліміт місць, одноразовий QR з **підписаним токеном** (HMAC), deep-link `t.me/bot?start=gl_<id>_<hmac>` (без крапки — Telegram інакше ігнорує `start`) — охорона сканує камерою смартфона
- ✅ Валідація: 3 статуси — «✅ дійсний» (квиток гаситься), «❌ вже використано» (з часом погашення), «❌ час вийшов»
- ✅ «Мертві душі»: 3 невикористаних квитки поспіль → авто-блокування Guest List на 30 днів (sweep при кожній спробі запису + команда адміна)
- ✅ Афіша: події з постерами, адмін додає/видаляє без програміста
- ✅ Меню: адмін завантажує PDF/фото, гості бачать його кнопкою
- ✅ Бронювання столів: схема залу (генерується автоматично), дата → кількість гостей → побажання, заявка летить адміну з телефоном клієнта
- ✅ Розсилки: текст + фото, з фільтром «користувачі Guest List»
- ✅ Захист: HMAC-підпис QR, прив'язка квитка до акаунта, rate-limit (анти-накрутка)
- ✅ Статистика, блокування/розблокування, закриття запису, зміна ліміту

## Запуск (локально)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows
# .venv/bin/python -m pip install -r requirements.txt        # Linux/macOS

cp .env.example .env        # впишите BOT_TOKEN, ADMIN_IDS, SECRET_KEY
.venv/Scripts/python -m versal
```

БД за замовчуванням — SQLite (`data/versal.db`), для продакшена підставте PostgreSQL.

## Запуск через Docker (+ PostgreSQL)

```bash
cp .env.example .env   # впишите BOT_TOKEN, ADMIN_IDS, SECRET_KEY
docker compose up --build
```

## Швидкий тест логіки без Telegram

```bash
.venv/Scripts/python scripts/smoke_test.py
```

## Структура

```
versal/
├── main.py          # точка входу, команди бота
├── config.py        # налаштування з .env
├── texts.py         # всі тексти бота
├── keyboards.py     # клавіатури
├── db/              # SQLAlchemy: моделі, репозиторій
├── services/        # QR, токени, rate-limit, схема залу
└── handlers/        # start, guest_list, afisha, menu, reservations, validation, admin
```

## Команди адміністратора

`/admin` — панель; `/set_limit 150`; `/close_gl`; `/open_gl`; `/del_event 3`; `/unblock 123456789`; `/reserve_info 5`; `/scan <токен>` — для охорони.
