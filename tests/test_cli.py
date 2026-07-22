from monitor.cli import main
from monitor.db import get_connection, init_db
from monitor.groups import sync_groups


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


def test_groups_list_prints_groups(tmp_path, capsys, monkeypatch):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["groups", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Soporte Acme" in captured.out
    assert "1@g.us" in captured.out


def test_groups_exclude_marks_group_excluded(tmp_path, monkeypatch):
    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["groups", "exclude", "1@g.us"])
    assert exit_code == 0

    conn = get_connection(db_path)
    row = conn.execute("SELECT excluded FROM groups WHERE group_id = ?", ("1@g.us",)).fetchone()
    assert row[0] == 1


def test_needs_review_list_prints_flagged_threads(tmp_path, capsys, monkeypatch):
    from datetime import datetime, timezone
    from monitor.threads import Message, mark_needs_review, upsert_message

    db_path = str(tmp_path / "monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "1@g.us", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, 10)
    mark_needs_review(conn, "1@g.us", "s1", now, 10)
    conn.close()

    monkeypatch.setenv("MONITOR_DB_PATH", db_path)
    exit_code = main(["needs-review", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "1@g.us" in captured.out
    assert "s1" in captured.out
    assert "Juan" in captured.out
