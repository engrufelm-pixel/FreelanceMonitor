# FreelanceMonitor

Telegram-бот, который агрегирует задачи с фриланс-бирж (Kwork / YouDo / Profi.ru / FL.ru), оценивает их через GPT по матрице навыков разработчика и присылает в Telegram только релевантное — карточками с кнопками «Открыть / Сгенерировать отклик / Сменить тональность / Скрыть».

## Стек

- Python 3.11, aiogram 3.x
- Playwright + playwright-stealth (парсинг)
- aiosqlite (SQLite)
- AITunnel (OpenAI-совместимый API) — модель `gpt-4o-mini`

## Возможности

- 4 источника задач, опрашиваются каждые ~30 минут с джиттером
- Скоринг задач по шкале 0–100 на основе матрицы навыков (`DEVELOPER_PROFILE`)
- Маршрутизация по score: `≥60` — мгновенный пуш, `40–59` — часовой дайджест, `<40` — только в БД для антидубля
- Fuzzy-дедупликация по заголовку + бюджету (порог 0.95) за 14 дней
- Генерация откликов в трёх стилях: `короче / увереннее / сбалансированно`
- Reply-клавиатура: `📊 Статус · 🔄 Проверить биржи · 🍪 Импорт Cookies`
- Импорт cookies Profi.ru через документ в чат

## Установка

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
cp .env.example .env   # и заполнить ключи
```

## Конфигурация (`.env`)

```env
ADMIN_ID=<твой Telegram ID>
BOT_TOKEN=<токен от @BotFather>
AITUNNEL_API_KEY=<ключ AITunnel>
AITUNNEL_BASE_URL=https://api.aitunnel.ru/v1
AI_MODEL=gpt-4o-mini
DB_PATH=database/bot.db
DEFAULT_MIN_BUDGET=2000
DEFAULT_CHECK_INTERVAL=30
```

## Запуск

```bash
python main.py
```

В Telegram отправь боту `/start` — появится постоянная Reply-клавиатура.

## Cookies для Profi.ru

1. Установи расширение **Cookie-Editor** в Chrome / Firefox.
2. Открой profi.ru под своим аккаунтом → Cookie-Editor → **Export → JSON**.
3. Пришли файл боту (или нажми кнопку «🍪 Импорт Cookies»).

## Сброс БД

```bash
python scripts/clear_db.py --yes
```

Или в Telegram — скрытая команда `/reset_db` с inline-подтверждением.

## Структура

```
FreelanceMonitor/
├── main.py
├── config.py                 # AITunnel, ADMIN_ID, DEVELOPER_PROFILE
├── database/
│   ├── models.py             # init_db, tasks/processed_tasks/actions
│   └── db_utils.py           # CRUD + fuzzy-дедуп + clear_all
├── handlers/
│   ├── admin.py              # Reply-клавиатура, /start /status /check /reset_db
│   └── tasks.py              # карточки + кнопки pitch/tone/hide
├── parsers/
│   ├── kwork_parser.py       # .want-card
│   ├── youdo_parser.py       # TasksList_listItem
│   ├── profi_parser.py       # cookies-based
│   └── fl_parser.py          # RSS + HTML fallback
├── services/
│   └── monitor.py            # run_check + monitor_loop + часовой дайджест
├── utils/
│   ├── ai_assistant.py       # AsyncOpenAI → AITunnel
│   └── keyboards.py
└── scripts/
    └── clear_db.py
```
