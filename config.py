import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

# ── AITunnel (OpenAI-совместимый) ──
AITUNNEL_API_KEY: str = os.getenv("AITUNNEL_API_KEY", "")
AITUNNEL_BASE_URL: str = os.getenv("AITUNNEL_BASE_URL", "https://api.aitunnel.ru/v1")
AI_MODEL: str = os.getenv("AI_MODEL", "gpt-4o-mini")

# ── База данных ──
_PROJECT_ROOT = Path(__file__).parent
_db_env = os.getenv("DB_PATH", "database/bot.db")
# Если в .env прописан относительный путь — резолвим от корня проекта,
# чтобы скрипты работали из любого CWD.
DB_PATH: str = _db_env if Path(_db_env).is_absolute() else str(_PROJECT_ROOT / _db_env)

# ── Настройки по умолчанию ──
DEFAULT_MIN_BUDGET: int = int(os.getenv("DEFAULT_MIN_BUDGET", "2000"))
DEFAULT_CHECK_INTERVAL: int = int(os.getenv("DEFAULT_CHECK_INTERVAL", "30"))

# ── Матрица навыков для AI-скоринга ──
DEVELOPER_PROFILE = """Независимый Python-разработчик и интегратор.

Навыки:
- Python 3.11, aiogram 3.x (Telegram-боты с FSM, инлайн-меню, AI-интеграциями)
- FastAPI, REST API, webhooks, CRUD
- SQLite, PostgreSQL
- Парсинг и автоматизация: Playwright, BeautifulSoup, requests, выгрузка в Excel/CSV/Google Sheets
- API-интеграции: Google Sheets API, VK API, OpenAI/Anthropic API, AmoCRM, Bitrix24
- Чистый HTML/CSS/JS лендинги без конструкторов

Принцип: MVP за 2-5 дней. Сдаю рабочий инструмент, который сразу экономит время.

Цены:
- Telegram-боты: 5 000-15 000 ₽
- Сайты/лендинги: 6 000-15 000 ₽
- Парсеры/автоматизация: 3 000-10 000 ₽

НЕ работает с: WordPress, Битрикс, мобильные приложения iOS/Android, крипта, хайлоад, геймдев."""
