import aiosqlite

from config import DB_PATH

CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    budget INTEGER DEFAULT 0,
    url TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    score_reason TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source, external_id)
);
"""

CREATE_PROCESSED = """
CREATE TABLE IF NOT EXISTS processed_tasks (
    url_hash TEXT PRIMARY KEY,
    title_norm TEXT,
    budget INTEGER,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_ACTIONS = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_processed_title ON processed_tasks(title_norm);",
    "CREATE INDEX IF NOT EXISTS idx_processed_created ON processed_tasks(created_at);",
]


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TASKS)
        await db.execute(CREATE_PROCESSED)
        await db.execute(CREATE_ACTIONS)
        for sql in CREATE_INDEXES:
            await db.execute(sql)
        await db.commit()
