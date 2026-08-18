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
        "SELECT group_id, name, excluded, kappa_client_id, kappa_project_id FROM groups ORDER BY name"
    ).fetchall()
    return [
        {
            "group_id": r[0],
            "name": r[1],
            "excluded": bool(r[2]),
            "kappa_client_id": r[3],
            "kappa_project_id": r[4],
        }
        for r in rows
    ]


def get_group_mapping(conn, group_id: str) -> dict:
    row = conn.execute(
        "SELECT kappa_client_id, kappa_project_id FROM groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        return {"kappa_client_id": None, "kappa_project_id": None}
    return {"kappa_client_id": row[0], "kappa_project_id": row[1]}


def set_group_mapping(conn, group_id: str, kappa_client_id: int | None, kappa_project_id: int | None) -> None:
    conn.execute(
        "UPDATE groups SET kappa_client_id = ?, kappa_project_id = ? WHERE group_id = ?",
        (kappa_client_id, kappa_project_id, group_id),
    )
    conn.commit()
