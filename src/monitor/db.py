import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    excluded INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    group_id TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    sender_name TEXT,
    messages_json TEXT NOT NULL DEFAULT '[]',
    last_activity_at TEXT NOT NULL,
    deadline_at TEXT NOT NULL,
    ticketed INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, sender_id)
);

CREATE TABLE IF NOT EXISTS seen_messages (
    message_id TEXT PRIMARY KEY
);
"""


def get_connection(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return sqlite3.connect(db_path, check_same_thread=check_same_thread)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
