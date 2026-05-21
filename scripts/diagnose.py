"""Диагностика: гоняет каждый парсер по очереди, показывает счётчики и первые ошибки.

Запуск:
    python scripts/diagnose.py
"""
import asyncio
import io
import logging
import sys
import traceback
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Покажем все INFO-логи парсеров — увидим что они говорят сами о себе
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from parsers.fl_parser import fetch_fl_tasks
from parsers.kwork_parser import fetch_kwork_tasks
from parsers.profi_parser import fetch_profi_tasks
from parsers.youdo_parser import fetch_youdo_tasks

PARSERS = [
    ("FL.ru", fetch_fl_tasks),
    ("Kwork", fetch_kwork_tasks),
    ("YouDo", fetch_youdo_tasks),
    ("Profi.ru", fetch_profi_tasks),
]


async def main() -> None:
    print("=" * 60)
    print("ДИАГНОСТИКА ПАРСЕРОВ FreelanceMonitor")
    print("=" * 60)

    # Сразу проверим, есть ли cookies и chromium
    from parsers.profi_parser import COOKIES_FILE

    print(f"\nProfi cookies: {'есть' if COOKIES_FILE.exists() else 'НЕТ'} → {COOKIES_FILE}")

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            try:
                b = await p.chromium.launch(headless=True)
                ver = b.version
                await b.close()
                print(f"Chromium: OK (версия {ver})")
            except Exception as e:
                print(f"Chromium: НЕ ЗАПУСКАЕТСЯ → {e}")
                print("       Скорее всего нужно: .venv/Scripts/playwright install chromium")
                return
    except ImportError as e:
        print(f"Playwright не установлен: {e}")
        return

    results = {}
    for name, fn in PARSERS:
        print(f"\n{'─' * 60}\n>>> {name}")
        try:
            tasks = await fn()
            with_b = sum(1 for t in tasks if t.get("budget"))
            results[name] = {"count": len(tasks), "with_budget": with_b}
            print(f"<<< {name}: {len(tasks)} задач (с бюджетом: {with_b})")
            for t in tasks[:2]:
                print(f"    · {t.get('budget', 0):>8} ₽ | {t.get('title', '')[:80]}")
        except Exception:
            print(f"<<< {name}: КРИТИЧЕСКИЙ СБОЙ")
            traceback.print_exc()
            results[name] = {"count": 0, "with_budget": 0, "error": True}

    print(f"\n{'=' * 60}")
    print("ИТОГИ:")
    for name, r in results.items():
        mark = "✓" if r["count"] > 0 else "✗"
        print(f"  {mark} {name:10}: {r['count']:>3} задач  ({r['with_budget']} с бюджетом)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
