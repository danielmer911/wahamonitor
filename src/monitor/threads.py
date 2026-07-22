import json
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Message:
    message_id: str
    text: str
    media: dict | None
    timestamp: str


@dataclass
class ThreadRecord:
    group_id: str
    sender_id: str
    sender_name: str
    messages: list[Message]
    last_activity_at: str
    deadline_at: str


def _row_to_thread(row) -> ThreadRecord:
    group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at = row
    messages = [Message(**m) for m in json.loads(messages_json)]
    return ThreadRecord(group_id, sender_id, sender_name, messages, last_activity_at, deadline_at)


def upsert_message(
    conn,
    group_id: str,
    sender_id: str,
    sender_name: str,
    message: Message,
    now: datetime,
    inactivity_minutes: int,
) -> bool:
    seen = conn.execute(
        "SELECT 1 FROM seen_messages WHERE message_id = ?", (message.message_id,)
    ).fetchone()
    if seen:
        return False
    conn.execute("INSERT INTO seen_messages (message_id) VALUES (?)", (message.message_id,))

    deadline_at = (now + timedelta(minutes=inactivity_minutes)).isoformat()
    row = conn.execute(
        "SELECT messages_json FROM threads WHERE group_id = ? AND sender_id = ?",
        (group_id, sender_id),
    ).fetchone()

    if row is None:
        messages_json = json.dumps([message.__dict__])
        conn.execute(
            """
            INSERT INTO threads
                (group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at, ticketed, needs_review)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (group_id, sender_id, sender_name, messages_json, now.isoformat(), deadline_at),
        )
    else:
        existing = json.loads(row[0])
        existing.append(message.__dict__)
        conn.execute(
            """
            UPDATE threads
            SET messages_json = ?, last_activity_at = ?, deadline_at = ?, ticketed = 0
            WHERE group_id = ? AND sender_id = ?
            """,
            (json.dumps(existing), now.isoformat(), deadline_at, group_id, sender_id),
        )
    conn.commit()
    return True


def get_due_threads(conn, now: datetime) -> list[ThreadRecord]:
    rows = conn.execute(
        """
        SELECT group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at
        FROM threads
        WHERE ticketed = 0 AND deadline_at <= ?
        """,
        (now.isoformat(),),
    ).fetchall()
    return [_row_to_thread(row) for row in rows]


def mark_ticketed(conn, group_id: str, sender_id: str) -> None:
    conn.execute(
        "UPDATE threads SET ticketed = 1, needs_review = 0 WHERE group_id = ? AND sender_id = ?",
        (group_id, sender_id),
    )
    conn.commit()


def mark_needs_review(conn, group_id: str, sender_id: str, now: datetime, inactivity_minutes: int) -> None:
    deadline_at = (now + timedelta(minutes=inactivity_minutes)).isoformat()
    conn.execute(
        "UPDATE threads SET needs_review = 1, deadline_at = ? WHERE group_id = ? AND sender_id = ?",
        (deadline_at, group_id, sender_id),
    )
    conn.commit()


def reset_deadline(conn, group_id: str, sender_id: str, now: datetime, inactivity_minutes: int) -> None:
    deadline_at = (now + timedelta(minutes=inactivity_minutes)).isoformat()
    conn.execute(
        "UPDATE threads SET deadline_at = ?, needs_review = 0 WHERE group_id = ? AND sender_id = ?",
        (deadline_at, group_id, sender_id),
    )
    conn.commit()


def get_stale_threads(conn, now: datetime, max_lifetime_minutes: int) -> list[ThreadRecord]:
    rows = conn.execute(
        """
        SELECT group_id, sender_id, sender_name, messages_json, last_activity_at, deadline_at
        FROM threads
        WHERE ticketed = 0
        """
    ).fetchall()
    threads = [_row_to_thread(row) for row in rows]
    stale = []
    for thread in threads:
        first_timestamp = datetime.fromisoformat(thread.messages[0].timestamp)
        age_minutes = (now - first_timestamp).total_seconds() / 60
        if age_minutes >= max_lifetime_minutes:
            stale.append(thread)
    return stale


def archive_thread(conn, group_id: str, sender_id: str) -> None:
    mark_ticketed(conn, group_id, sender_id)
