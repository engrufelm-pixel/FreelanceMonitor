"""Полная очистка БД FreelanceMonitor. Использовать перед чистым стартом на сервере.

Запуск:
    python scripts/clear_db.py        # с интерактивным подтверждением
    python scripts/clear_db.py --yes  # без подтверждения (для скриптов)

⚠️  Перед запуском остановите работающий процесс main.py — иначе SQLite может
вернуть «database is locked».
"""
import asyncio
import io
import sys
from pathlib import Path

# Принудительный UTF-8 stdout (Windows cp1251 не выводит эмодзи)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Подключаем корень проекта к sys.path, чтобы импорты работали
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.db_utils import clear_all
from database.models import init_db


async def main() -> None:
    auto_yes = "--yes" in sys.argv or "-y" in sys.argv

    await init_db()  # на случай, если БД ещё не создана

    if not auto_yes:
        print("⚠️  Эта операция удалит ВСЕ задачи, историю дедупликации и лог действий.")
        ans = input("Продолжить? [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    before = await clear_all()
    print("🧹 БД очищена:")
    for table, n in before.items():
        print(f"  {table}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
