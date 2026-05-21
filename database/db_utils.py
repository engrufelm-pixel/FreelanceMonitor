import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Optional

import aiosqlite

from config import DB_PATH

# ── Статусы задач ──
STATUS_NEW = "new"
STATUS_READY = "ready_to_send"
STATUS_SENT = "sent"
STATUS_HIDDEN = "hidden"
STATUS_DIGEST = "digest"

# ── Действия пользователя ──
ACTION_CLICK = "click"
ACTION_RESPOND = "respond"
ACTION_HIDE = "hide"
ACTION_RETONE = "retone"

# Порог fuzzy-сравнения заголовков (0..1)
FUZZY_THRESHOLD = 0.95
# Окно дедупликации по fuzzy — задачи старше игнорируются
FUZZY_WINDOW_DAYS = 14


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower().strip())


def _url_hash(url: str) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()


async def is_duplicate(url: str, title: str, budget: int = 0) -> bool:
    """True если URL уже видели ИЛИ fuzzy-сходство по title >= 0.95 при близком бюджете."""
    url_h = _url_hash(url)
    title_norm = _norm_title(title)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM processed_tasks WHERE url_hash = ? LIMIT 1", (url_h,)
        )
        if await cur.fetchone():
            return True

        cur = await db.execute(
            f"SELECT title_norm, budget FROM processed_tasks "
            f"WHERE created_at > datetime('now', '-{FUZZY_WINDOW_DAYS} days')"
        )
        rows = await cur.fetchall()

    for stored_title, stored_budget in rows:
        if not stored_title:
            continue
        sim = SequenceMatcher(None, title_norm, stored_title).ratio()
        if sim < FUZZY_THRESHOLD:
            continue
        # Бюджеты: если оба известны — должны быть в пределах 20%
        if budget and stored_budget:
            if abs(budget - stored_budget) / max(budget, stored_budget) > 0.2:
                continue
        return True
    return False


async def insert_task(
    source: str,
    external_id: str,
    title: str,
    description: str,
    budget: int,
    url: str,
    score: int,
    score_reason: str,
    status: str = STATUS_NEW,
) -> Optional[int]:
    """Создаёт запись в tasks + processed_tasks. Возвращает id или None при конфликте по UNIQUE."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                """
                INSERT INTO tasks
                    (source, external_id, title, description, budget, url, score, score_reason, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, external_id, title, description, budget, url, score, score_reason, status),
            )
            task_id = cur.lastrowid
            await db.execute(
                """
                INSERT OR IGNORE INTO processed_tasks (url_hash, title_norm, budget, source)
                VALUES (?, ?, ?, ?)
                """,
                (_url_hash(url), _norm_title(title), budget, source),
            )
            await db.commit()
            return task_id
        except aiosqlite.IntegrityError:
            return None


async def update_status(task_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        await db.commit()


async def log_action(task_id: int, action_type: str, payload: dict | None = None) -> None:
    payload_str = json.dumps(payload, ensure_ascii=False) if payload else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO actions (task_id, action_type, payload) VALUES (?, ?, ?)",
            (task_id, action_type, payload_str),
        )
        await db.commit()


async def get_task(task_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_stats() -> dict:
    """Сводка по БД: счётчики по статусам, по источникам, последняя проверка."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        by_status = {
            r["status"]: r["c"]
            for r in await (
                await db.execute(
                    "SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"
                )
            ).fetchall()
        }
        by_source = {
            r["source"]: r["c"]
            for r in await (
                await db.execute(
                    "SELECT source, COUNT(*) AS c FROM tasks GROUP BY source ORDER BY c DESC"
                )
            ).fetchall()
        }
        last = await (
            await db.execute("SELECT MAX(created_at) AS t FROM tasks")
        ).fetchone()
        total = await (
            await db.execute("SELECT COUNT(*) AS c FROM processed_tasks")
        ).fetchone()
        return {
            "by_status": by_status,
            "by_source": by_source,
            "last_seen_at": last["t"] if last else None,
            "processed_total": total["c"] if total else 0,
        }


async def clear_all() -> dict:
    """Полная очистка tasks + processed_tasks + actions. Возвращает счётчики удалённого."""
    async with aiosqlite.connect(DB_PATH) as db:
        before = {}
        for table in ("tasks", "processed_tasks", "actions"):
            cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cur.fetchone()
            before[table] = row[0] if row else 0

        for table in ("tasks", "processed_tasks", "actions"):
            await db.execute(f"DELETE FROM {table}")
        # Сброс автоинкремента
        await db.execute("DELETE FROM sqlite_sequence WHERE name IN ('tasks','actions')")
        await db.commit()
        return before


async def get_pending_for_digest() -> list[dict]:
    """Задачи со score 40-59 за последний час, ещё в digest-очереди."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
              AND created_at > datetime('now', '-1 hour')
            ORDER BY score DESC
            """,
            (STATUS_DIGEST,),
        )
        return [dict(r) for r in await cur.fetchall()]
