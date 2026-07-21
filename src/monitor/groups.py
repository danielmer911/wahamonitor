from datetime import datetime, timezone


def sync_groups(conn, waha_client) -> int:
    now = datetime.now(timezone.utc).isoformat()
    remote_groups = waha_client.list_groups()

    for group in remote_groups:
        conn.execute(
            """
            INSERT INTO groups (group_id, name, excluded, last_synced_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                name = excluded.name,
                last_synced_at = excluded.last_synced_at
            """,
            (group["id"], group["name"], now),
        )
    conn.commit()
    return len(remote_groups)


def exclude_group(conn, group_id: str) -> None:
    conn.execute("UPDATE groups SET excluded = 1 WHERE group_id = ?", (group_id,))
    conn.commit()


def include_group(conn, group_id: str) -> None:
    conn.execute("UPDATE groups SET excluded = 0 WHERE group_id = ?", (group_id,))
    conn.commit()


def is_excluded(conn, group_id: str) -> bool:
    row = conn.execute(
        "SELECT excluded FROM groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    return bool(row[0]) if row else False


def list_groups(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT group_id, name, excluded FROM groups ORDER BY name"
    ).fetchall()
    return [
        {"group_id": r[0], "name": r[1], "excluded": bool(r[2])} for r in rows
    ]
