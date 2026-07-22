from datetime import datetime, timedelta, timezone

from monitor.db import get_connection, init_db
from monitor.threads import (
    Message,
    archive_thread,
    get_due_threads,
    get_stale_threads,
    mark_needs_review,
    mark_ticketed,
    reset_deadline,
    upsert_message,
)


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_upsert_message_creates_new_thread(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    msg = Message(message_id="m1", text="Hola, tengo un problema", media=None, timestamp=now.isoformat())

    applied = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)

    assert applied is True
    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert len(due) == 1
    assert due[0].group_id == "g1"
    assert due[0].sender_id == "s1"
    assert due[0].sender_name == "Juan"
    assert [m.message_id for m in due[0].messages] == ["m1"]


def test_upsert_message_deduplicates_by_message_id(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    msg = Message(message_id="m1", text="Hola", media=None, timestamp=now.isoformat())

    first = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)
    second = upsert_message(conn, "g1", "s1", "Juan", msg, now, inactivity_minutes=10)

    assert first is True
    assert second is False
    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert len(due[0].messages) == 1


def test_interleaved_senders_are_segmented_independently(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)

    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Problema A", None, now.isoformat()), now, 10)
    upsert_message(conn, "g1", "s2", "Maria", Message("m2", "Problema B", None, now.isoformat()), now, 10)
    upsert_message(conn, "g1", "s1", "Juan", Message("m3", "Mas detalles A", None, now.isoformat()), now, 10)

    due = get_due_threads(conn, now + timedelta(minutes=11))
    by_sender = {t.sender_id: t for t in due}

    assert set(by_sender) == {"s1", "s2"}
    assert [m.message_id for m in by_sender["s1"].messages] == ["m1", "m3"]
    assert [m.message_id for m in by_sender["s2"].messages] == ["m2"]


def test_get_due_threads_excludes_threads_before_deadline(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    due = get_due_threads(conn, now + timedelta(minutes=5))

    assert due == []


def test_mark_ticketed_excludes_thread_from_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    mark_ticketed(conn, "g1", "s1")

    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert due == []


def test_reset_deadline_pushes_thread_out_of_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    reset_deadline(conn, "g1", "s1", now + timedelta(minutes=9), inactivity_minutes=10)

    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert due == []


def test_mark_needs_review_pushes_deadline_out_of_due_list(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    due_at = now + timedelta(minutes=11)
    mark_needs_review(conn, "g1", "s1", due_at, inactivity_minutes=10)

    # Immediately after being marked, the thread should NOT reappear (backoff applied)
    due = get_due_threads(conn, due_at)
    assert due == []

    # But after the backoff window elapses, it becomes due again
    due_later = get_due_threads(conn, due_at + timedelta(minutes=11))
    assert len(due_later) == 1


def test_mark_needs_review_flag_clears_when_ticketed(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    mark_needs_review(conn, "g1", "s1", now, inactivity_minutes=10)
    row = conn.execute("SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")).fetchone()
    assert row[0] == 1

    mark_ticketed(conn, "g1", "s1")
    row = conn.execute("SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")).fetchone()
    assert row[0] == 0


def test_mark_needs_review_flag_clears_when_deadline_reset(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    mark_needs_review(conn, "g1", "s1", now, inactivity_minutes=10)
    row = conn.execute("SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")).fetchone()
    assert row[0] == 1

    reset_deadline(conn, "g1", "s1", now, inactivity_minutes=10)
    row = conn.execute("SELECT needs_review FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")).fetchone()
    assert row[0] == 0


def test_get_stale_threads_returns_threads_past_max_lifetime(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    old_start = now - timedelta(minutes=300)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, old_start.isoformat()), old_start, inactivity_minutes=10)
    # a fresh thread that should NOT be stale
    upsert_message(conn, "g1", "s2", "Maria", Message("m2", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    stale = get_stale_threads(conn, now, max_lifetime_minutes=240)

    assert [t.sender_id for t in stale] == ["s1"]


def test_get_stale_threads_excludes_already_ticketed(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    old_start = now - timedelta(minutes=300)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, old_start.isoformat()), old_start, inactivity_minutes=10)
    mark_ticketed(conn, "g1", "s1")

    stale = get_stale_threads(conn, now, max_lifetime_minutes=240)

    assert stale == []


def test_archive_thread_marks_ticketed_without_writing_ticket(tmp_path):
    conn = make_conn(tmp_path)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    upsert_message(conn, "g1", "s1", "Juan", Message("m1", "Hola", None, now.isoformat()), now, inactivity_minutes=10)

    archive_thread(conn, "g1", "s1")

    row = conn.execute("SELECT ticketed FROM threads WHERE group_id = ? AND sender_id = ?", ("g1", "s1")).fetchone()
    assert row[0] == 1
    due = get_due_threads(conn, now + timedelta(minutes=11))
    assert due == []
