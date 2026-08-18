import sqlite3
from datetime import datetime, timezone

import pytest

from monitor.db import get_connection, init_db
from monitor.kappa_tickets import has_existing_kappa_ticket, record_kappa_ticket


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_has_existing_kappa_ticket_false_when_none_recorded(tmp_path):
    conn = make_conn(tmp_path)
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is False


def test_record_and_check_existing_kappa_ticket(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    record_kappa_ticket(conn, "g1", "s1", "m1", 203, "token-abc", now)

    assert has_existing_kappa_ticket(conn, "g1", "s1", "m1") is True
    assert has_existing_kappa_ticket(conn, "g1", "s1", "m2") is False
    assert has_existing_kappa_ticket(conn, "g1", "s2", "m1") is False


def test_record_kappa_ticket_twice_for_same_key_raises(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    record_kappa_ticket(conn, "g1", "s1", "m1", 203, "token-abc", now)

    with pytest.raises(sqlite3.IntegrityError):
        record_kappa_ticket(conn, "g1", "s1", "m1", 999, "token-xyz", now)
