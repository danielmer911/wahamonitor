import argparse
import os

from monitor.db import get_connection, init_db
from monitor.groups import exclude_group, include_group, list_groups


def _connect():
    db_path = os.environ.get("MONITOR_DB_PATH", "data/monitor.db")
    conn = get_connection(db_path)
    init_db(conn)
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    groups_parser = subparsers.add_parser("groups")
    groups_sub = groups_parser.add_subparsers(dest="groups_command", required=True)
    groups_sub.add_parser("list")
    exclude_parser = groups_sub.add_parser("exclude")
    exclude_parser.add_argument("group_id")
    include_parser = groups_sub.add_parser("include")
    include_parser.add_argument("group_id")

    review_parser = subparsers.add_parser("needs-review")
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("list")

    args = parser.parse_args(argv)
    conn = _connect()

    if args.command == "groups":
        if args.groups_command == "list":
            for group in list_groups(conn):
                status = "excluded" if group["excluded"] else "active"
                print(f"{group['group_id']}\t{group['name']}\t{status}")
        elif args.groups_command == "exclude":
            exclude_group(conn, args.group_id)
            print(f"Excluded {args.group_id}")
        elif args.groups_command == "include":
            include_group(conn, args.group_id)
            print(f"Included {args.group_id}")
        return 0

    if args.command == "needs-review":
        if args.review_command == "list":
            rows = conn.execute(
                "SELECT group_id, sender_id, sender_name FROM threads WHERE needs_review = 1"
            ).fetchall()
            for group_id, sender_id, sender_name in rows:
                print(f"{group_id}\t{sender_id}\t{sender_name}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
