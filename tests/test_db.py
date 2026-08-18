import os
import sqlite3

import pytest

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


def test_groups_table_has_kappa_mapping_columns(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO groups (group_id, name, excluded, last_synced_at, kappa_client_id, kappa_project_id) "
        "VALUES (?, ?, 0, ?, ?, ?)",
        ("g1", "Test Group", "2026-08-12T00:00:00", 60, 192),
    )
    conn.commit()

    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", ("g1",)
    ).fetchone()
    assert row == (60, 192)


def test_groups_kappa_mapping_columns_default_to_null(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO groups (group_id, name, excluded, last_synced_at) VALUES (?, ?, 0, ?)",
        ("g2", "Another Group", "2026-08-12T00:00:00"),
    )
    conn.commit()

    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", ("g2",)
    ).fetchone()
    assert row == (None, None)


def test_kappa_tickets_table_enforces_unique_constraint(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)

    conn.execute(
        "INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("g1", "s1", "m1", 203, "token-abc", "2026-08-12T00:00:00"),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("g1", "s1", "m1", 999, "token-xyz", "2026-08-12T01:00:00"),
        )
