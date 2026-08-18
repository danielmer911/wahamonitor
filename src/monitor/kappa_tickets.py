from datetime import datetime


def has_existing_kappa_ticket(conn, group_id: str, sender_id: str, last_message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM kappa_tickets WHERE group_id = ? AND sender_id = ? AND last_message_id = ?",
        (group_id, sender_id, last_message_id),
    ).fetchone()
    return row is not None


def record_kappa_ticket(
    conn,
    group_id: str,
    sender_id: str,
    last_message_id: str,
    kappa_ticket_id: int,
    kappa_token: str | None,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO kappa_tickets (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (group_id, sender_id, last_message_id, kappa_ticket_id, kappa_token, now.isoformat()),
    )
    conn.commit()
