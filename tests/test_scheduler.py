from datetime import datetime, timezone

from monitor.db import get_connection, init_db
from monitor.evaluator import TicketDecision
from monitor.scheduler import process_due_threads
from monitor.threads import Message, upsert_message


class FakeLLM:
    def generate(self, prompt: str) -> str:
        raise AssertionError("evaluator functions are patched directly in these tests")


class FakeWahaClient:
    def download_media(self, media_url: str) -> bytes:
        return b"data"


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_process_due_threads_writes_ticket_when_worthy(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(True, "resumen", "problema detallado"),
    )
    written_folders = []
    monkeypatch.setattr(
        "monitor.scheduler.write_ticket",
        lambda tickets_dir, group_name, thread, decision, waha_client, now: written_folders.append(group_name) or "folder",
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    assert written_folders == ["Soporte Acme"]

    from monitor.threads import get_due_threads
    assert get_due_threads(conn, later) == []


def test_process_due_threads_resets_deadline_when_not_worthy(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(False, "", ""),
    )

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    from monitor.threads import get_due_threads
    assert get_due_threads(conn, later) == []  # deadline was pushed out
    assert get_due_threads(conn, later + __import__("datetime").timedelta(minutes=11)) != []


def test_process_due_threads_marks_needs_review_on_evaluation_error(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")

    def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("monitor.scheduler.deep_evaluate", boom)

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    assert processed == 1
    row = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row[0] == 1
