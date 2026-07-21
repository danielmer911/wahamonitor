import os
import sqlite3

from monitor.db import get_connection, init_db


def test_init_db_creates_expected_tables(tmp_path):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}

    assert {"groups", "threads", "seen_messages"} <= tables
    assert os.path.isfile(db_path)


def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    init_db(conn)  # must not raise

    conn.execute("INSERT INTO groups (group_id, name, excluded, last_synced_at) VALUES (?, ?, ?, ?)",
                 ("g1", "Test Group", 0, "2026-07-21T00:00:00"))
    conn.commit()
    row = conn.execute("SELECT name FROM groups WHERE group_id = ?", ("g1",)).fetchone()
    assert row[0] == "Test Group"


def test_get_connection_creates_parent_directory(tmp_path):
    db_path = str(tmp_path / "nested" / "dir" / "monitor.db")
    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection)
    assert os.path.isdir(tmp_path / "nested" / "dir")
