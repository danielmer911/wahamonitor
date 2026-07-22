from datetime import datetime, timedelta, timezone

from monitor.db import get_connection, init_db
from monitor.evaluator import TicketDecision
from monitor.scheduler import archive_stale_threads, process_due_threads
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


def test_process_due_threads_batch_isolation_with_mixed_outcomes(tmp_path, monkeypatch):
    """Test that one thread's failure doesn't prevent other threads in the batch from being processed."""
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)

    # Create two due threads
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)
    upsert_message(conn, "g1", "s2", "Maria", Message("m2", "Problema", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")

    # Make deep_evaluate fail for sender s1 but succeed for s2
    def selective_deep_evaluate(llm, mcp_context, thread):
        if thread.sender_id == "s1":
            raise RuntimeError("Evaluation failed for s1")
        return TicketDecision(True, "resumen", "problema detallado")

    monkeypatch.setattr("monitor.scheduler.deep_evaluate", selective_deep_evaluate)

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

    # Both threads should be processed
    assert processed == 2
    # One write_ticket should have been called (for s2)
    assert written_folders == ["Soporte Acme"]

    # s1 should be marked needs_review due to evaluation failure
    row_s1 = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row_s1[0] == 1

    # s2 should be marked ticketed (not needs_review)
    row_s2 = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s2")
    ).fetchone()
    assert row_s2[0] == 0


def test_process_due_threads_batch_isolation_write_ticket_failure(tmp_path, monkeypatch):
    """Test that write_ticket failures don't abort the batch and result in needs_review."""
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)

    # Create two due threads, both ticket-worthy
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema 1", None, now.isoformat()), now, inactivity_minutes=10)
    upsert_message(conn, "g1", "s2", "Maria", Message("m2", "Problema 2", None, now.isoformat()), now, inactivity_minutes=10)

    monkeypatch.setattr("monitor.scheduler.fetch_context", lambda *a, **k: "contexto")
    monkeypatch.setattr(
        "monitor.scheduler.deep_evaluate",
        lambda llm, mcp_context, thread: TicketDecision(True, "resumen", "problema detallado"),
    )

    write_ticket_calls = []

    # Make write_ticket fail for sender s1 but succeed for s2
    def selective_write_ticket(tickets_dir, group_name, thread, decision, waha_client, now):
        write_ticket_calls.append(thread.sender_id)
        if thread.sender_id == "s1":
            raise RuntimeError("WAHA media download failed")
        return "folder"

    monkeypatch.setattr("monitor.scheduler.write_ticket", selective_write_ticket)

    class Config:
        tickets_dir = str(tmp_path / "tickets")
        mcp_url = "https://waha.example.com/mcp"
        mcp_api_key = None
        default_inactivity_minutes = 10

    later = now + __import__("datetime").timedelta(minutes=11)
    processed = process_due_threads(
        conn, Config(), FakeWahaClient(), FakeLLM(), group_name_lookup={"g1": "Soporte Acme"}, now=later
    )

    # Both threads should be processed (write_ticket was attempted for both)
    assert processed == 2
    assert set(write_ticket_calls) == {"s1", "s2"}

    # s1 should be marked needs_review due to write_ticket failure
    row_s1 = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row_s1[0] == 1

    # s2 should be marked ticketed (not needs_review)
    row_s2 = conn.execute(
        "SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s2")
    ).fetchone()
    assert row_s2[0] == 0


def test_archive_stale_threads_archives_threads_past_max_lifetime(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    old_start = now - timedelta(minutes=300)
    upsert_message(
        conn, "g1", "s1", "Juan", Message("m1", "Viejo", None, old_start.isoformat()), old_start, inactivity_minutes=10
    )
    upsert_message(
        conn, "g1", "s2", "Maria", Message("m2", "Nuevo", None, now.isoformat()), now, inactivity_minutes=10
    )

    class Config:
        max_thread_lifetime_minutes = 240

    archived_count = archive_stale_threads(conn, Config(), now)

    assert archived_count == 1

    row_s1 = conn.execute(
        "SELECT ticketed FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")
    ).fetchone()
    assert row_s1[0] == 1

    row_s2 = conn.execute(
        "SELECT ticketed FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s2")
    ).fetchone()
    assert row_s2[0] == 0

    tickets_dir = tmp_path / "tickets"
    assert not tickets_dir.exists() or list(tickets_dir.iterdir()) == []
