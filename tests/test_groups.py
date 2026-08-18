from monitor.db import get_connection, init_db
from monitor.groups import (
    exclude_group,
    get_group_mapping,
    include_group,
    is_excluded,
    list_groups,
    set_group_mapping,
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
    assert groups == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": None,
            "kappa_project_id": None,
        }
    ]


def test_sync_groups_updates_name_without_resetting_excluded(tmp_path):
    conn = make_conn(tmp_path)
    waha = FakeWahaClient([{"id": "1@g.us", "name": "Old Name"}])
    sync_groups(conn, waha)
    exclude_group(conn, "1@g.us")

    waha_renamed = FakeWahaClient([{"id": "1@g.us", "name": "New Name"}])
    sync_groups(conn, waha_renamed)

    groups = list_groups(conn)
    assert groups == [
        {
            "group_id": "1@g.us",
            "name": "New Name",
            "excluded": True,
            "kappa_client_id": None,
            "kappa_project_id": None,
        }
    ]


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


def test_get_group_mapping_defaults_to_none_for_unknown_group(tmp_path):
    conn = make_conn(tmp_path)
    assert get_group_mapping(conn, "unknown@g.us") == {"kappa_client_id": None, "kappa_project_id": None}


def test_set_and_get_group_mapping(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))

    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=192)

    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": 60, "kappa_project_id": 192}


def test_set_group_mapping_can_clear_with_none(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))
    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=192)

    set_group_mapping(conn, "1@g.us", kappa_client_id=None, kappa_project_id=None)

    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": None, "kappa_project_id": None}


def test_list_groups_includes_kappa_mapping(tmp_path):
    conn = make_conn(tmp_path)
    sync_groups(conn, FakeWahaClient([{"id": "1@g.us", "name": "Soporte Acme"}]))
    set_group_mapping(conn, "1@g.us", kappa_client_id=60, kappa_project_id=None)

    groups = list_groups(conn)

    assert groups == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": 60,
            "kappa_project_id": None,
        }
    ]
