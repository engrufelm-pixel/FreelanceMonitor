import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from aiogram import Bot

from config import DEFAULT_CHECK_INTERVAL, DEFAULT_MIN_BUDGET
from database.db_utils import (
    STATUS_DIGEST,
    STATUS_HIDDEN,
    STATUS_READY,
    STATUS_SENT,
    get_pending_for_digest,
    insert_task,
    is_duplicate,
    update_status,
)
from parsers.fl_parser import fetch_fl_tasks
from parsers.kwork_parser import fetch_kwork_tasks
from parsers.profi_parser import fetch_profi_tasks
from parsers.youdo_parser import fetch_youdo_tasks
from utils.ai_assistant import score_task

logger = logging.getLogger(__name__)

# ── Пороги градации score (ТЗ) ──
THRESHOLD_INSTANT = 80   # >=80 — пушим сразу
THRESHOLD_PUSH = 60      # 60-79 — обычный пуш
THRESHOLD_DIGEST = 40    # 40-59 — копится в дайджест
# <40 — STATUS_HIDDEN (только в БД для антидубля)

# Список парсеров — порядок задаёт очерёдность опроса
Fetcher = Callable[[], Awaitable[list[dict]]]
FETCHERS: list[Fetcher] = [
    fetch_fl_tasks,
    fetch_kwork_tasks,
    fetch_youdo_tasks,
    fetch_profi_tasks,
]

# Межпарсерная пауза, чтобы не бить все биржи одновременно
INTER_FETCHER_DELAY = (10.0, 25.0)
# Джиттер между циклами поверх DEFAULT_CHECK_INTERVAL (секунды)
LOOP_JITTER = (30, 90)

# Состояние цикла дайджеста
_last_digest_at: datetime | None = None
DIGEST_INTERVAL = timedelta(hours=1)


def format_run_stats(stats: dict) -> str:
    """Красивая сводка после run_check для отправки в Telegram."""
    return (
        "✅ <b>Проверка завершена</b>\n"
        "─────────────────────────\n"
        f"📥 Собрано:      <b>{stats.get('fetched', 0)}</b>\n"
        f"🚀 Отправлено:   <b>{stats.get('sent', 0)}</b>\n"
        f"🟡 В дайджест:   <b>{stats.get('digest', 0)}</b>\n"
        f"🔴 Скрыто:       <b>{stats.get('hidden', 0)}</b>\n"
        f"♻️ Дубликатов:   <b>{stats.get('duplicate', 0)}</b>\n"
        f"⚠️ Ошибок:       <b>{stats.get('error', 0)}</b>"
    )


def _label(score: int) -> str:
    if score >= 90:
        return "⭐ ИДЕАЛЬНО"
    if score >= THRESHOLD_INSTANT:
        return "🚀 ОТЛИЧНО"
    if score >= THRESHOLD_PUSH:
        return "🟢 ПОДХОДИТ"
    if score >= THRESHOLD_DIGEST:
        return "🟡 НА ГРАНИ"
    return "🔴 ПРОПУЩЕНО"


async def _run_one_fetcher(fetcher: Fetcher) -> list[dict]:
    try:
        return await fetcher()
    except Exception as e:
        logger.error("%s: %s", fetcher.__name__, e, exc_info=True)
        return []


async def _collect_tasks() -> list[dict]:
    """Опрашивает все парсеры последовательно с межпарсерной паузой."""
    all_tasks: list[dict] = []
    for i, fetcher in enumerate(FETCHERS):
        if i > 0:
            await asyncio.sleep(random.uniform(*INTER_FETCHER_DELAY))
        tasks = await _run_one_fetcher(fetcher)
        all_tasks.extend(tasks)
    return all_tasks


async def _process_task(bot: Bot, admin_id: int, task: dict, min_budget: int) -> str:
    """Обрабатывает одну задачу: антидубль → AI-скор → маршрут. Возвращает статус-метку.

    Бюджетный отсев отключён: даже задачи с маленьким бюджетом идут к AI,
    решение принимает только score (≥60 пуш, 40–59 дайджест, <40 скрыто).
    """
    budget = int(task.get("budget") or 0)

    if await is_duplicate(task["url"], task["title"], budget):
        return "duplicate"

    score_result = await score_task(task["title"], task.get("description", ""), budget)
    score = score_result["score"]
    reason = score_result["reason"]

    if score >= THRESHOLD_PUSH:
        status = STATUS_READY
    elif score >= THRESHOLD_DIGEST:
        status = STATUS_DIGEST
    else:
        status = STATUS_HIDDEN

    task_id = await insert_task(
        source=task["source"],
        external_id=task["external_id"],
        title=task["title"],
        description=task.get("description", ""),
        budget=budget,
        url=task["url"],
        score=score,
        score_reason=reason,
        status=status,
    )
    if task_id is None:
        return "duplicate"

    if status == STATUS_READY:
        # Отправка карточки — Шаг 5 импортирует send_task_card отсюда
        from handlers.tasks import send_task_card

        await send_task_card(bot, admin_id, task_id)
        await update_status(task_id, STATUS_SENT)
        logger.info("Отправлено: [%d] %s — score=%d", task_id, task["title"][:60], score)
        return "sent"

    logger.info("В %s: [%d] %s — score=%d", status, task_id, task["title"][:60], score)
    return status


_DIGEST_DIVIDER = "─────────────────────────"
_SOURCE_ICON = {"Kwork": "🟠", "YouDo": "🔴", "Profi.ru": "🟢", "FL.ru": "🔵"}


async def _send_digest(bot: Bot, admin_id: int) -> int:
    """Шлёт сводку задач 40-59 за последний час. Возвращает их число."""
    import html as _html

    rows = await get_pending_for_digest()
    if not rows:
        return 0

    header = (
        f"🟡 <b>НА ГРАНИ · {len(rows)} {_pluralize(len(rows))}</b>\n"
        f"<i>за последний час · score 40–59</i>"
    )
    blocks = [header, _DIGEST_DIVIDER]

    for r in rows:
        icon = _SOURCE_ICON.get(r["source"], "🆕")
        budget = (
            f"{r['budget']:,} ₽".replace(",", " ") if r["budget"] else "—"
        )
        title = _html.escape((r["title"] or "")[:100])
        reason = _html.escape((r["score_reason"] or "")[:140])
        blocks.append(
            f"<b>{r['score']}/100</b>  ·  {icon} {r['source']}  ·  💰 {budget}\n"
            f"<b>{title}</b>\n"
            f"🎯 <i>{reason}</i>\n"
            f"🔗 <a href=\"{r['url']}\">открыть на бирже</a>"
        )

    text = "\n\n".join(blocks)
    await bot.send_message(admin_id, text, disable_web_page_preview=True)
    for r in rows:
        await update_status(r["id"], STATUS_SENT)
    return len(rows)


def _pluralize(n: int) -> str:
    n_abs = abs(n) % 100
    last = n_abs % 10
    if 11 <= n_abs <= 14:
        return "задач"
    if last == 1:
        return "задача"
    if 2 <= last <= 4:
        return "задачи"
    return "задач"


async def run_check(bot: Bot, admin_id: int) -> dict:
    """Один проход: собрать задачи → отфильтровать → разослать. Возвращает статистику."""
    stats = {
        "fetched": 0, "sent": 0, "digest": 0, "hidden": 0,
        "duplicate": 0, "low_budget": 0, "error": 0,
    }

    all_tasks = await _collect_tasks()
    stats["fetched"] = len(all_tasks)

    for t in all_tasks:
        try:
            result = await _process_task(bot, admin_id, t, DEFAULT_MIN_BUDGET)
            stats[result] = stats.get(result, 0) + 1
            await asyncio.sleep(0.5)  # лимит Telegram + лимит AITunnel
        except Exception as e:
            logger.error("Сбой обработки задачи %s: %s", t.get("url"), e, exc_info=True)
            stats["error"] += 1

    logger.info("Проверка завершена: %s", stats)
    return stats


async def monitor_loop(bot: Bot, admin_id: int) -> None:
    """Бесконечный цикл: run_check каждые DEFAULT_CHECK_INTERVAL минут + джиттер.
    Раз в час шлёт дайджест задач 40-59."""
    global _last_digest_at
    logger.info("Цикл мониторинга запущен")

    while True:
        try:
            await run_check(bot, admin_id)

            now = datetime.utcnow()
            if _last_digest_at is None or (now - _last_digest_at) >= DIGEST_INTERVAL:
                count = await _send_digest(bot, admin_id)
                _last_digest_at = now
                if count:
                    logger.info("Дайджест отправлен: %d задач", count)

            interval_sec = DEFAULT_CHECK_INTERVAL * 60 + random.randint(*LOOP_JITTER)
            logger.info("Следующая проверка через %d сек", interval_sec)
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.info("Мониторинг остановлен")
            break
        except Exception as e:
            logger.error("Ошибка в цикле мониторинга: %s", e, exc_info=True)
            await asyncio.sleep(60)
