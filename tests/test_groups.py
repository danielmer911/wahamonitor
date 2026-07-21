from monitor.db import get_connection, init_db
from monitor.groups import (
    exclude_group,
    include_group,
    is_excluded,
    list_groups,
    sync_groups,
)


class FakeWahaClient:
    def __init__(self, groups):
        self._groups = groups

    def list_groups(self):
        return self._groups


def make_conn(tmp_path):
    conn = get_connection(str(tmp_path / "monitor.db"))
    init_db(conn)
    return conn


def test_sync_groups_inserts_new_groups(tmp_path):
    conn = make_conn(tmp_path)
    waha = FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}])

    count = sync_groups(conn, waha)

    assert count == 1
    groups = list_groups(conn)
    assert groups == [{"group_id": "1@g.us", "name": "Soporte Acme", "excluded": False}]


def test_sync_groups_updates_name_without_resetting_excluded(tmp_path):
    conn = make_conn(tmp_path)
    waha = FakeWahaClient([{"id": "1@g.us", "name": "Old Name"}])
    sync_groups(conn, waha)
    exclude_group(conn, "1@g.us")

    waha_renamed = FakeWahaClient([{"id": "1@g.us", "name": "New Name"}])
    sync_groups(conn, waha_renamed)

    groups = list_groups(conn)
    assert groups == [{"group_id": "1@g.us", "name": "New Name", "excluded": True}]


def test_exclude_and_include_group(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "G"}]))

    exclude_group(conn, "1@g.us")
    assert is_excluded(conn, "1@g.us") is True

    include_group(conn, "1@g.us")
    assert is_excluded(conn, "1@g.us") is False


def test_is_excluded_unknown_group_is_false(tmp_path):
    conn = make_conn(tmp_path)
    assert is_excluded(conn, "unknown@g.us") is False
