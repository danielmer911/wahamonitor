from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.groups import sync_groups
from monitor.kappa_routes import create_kappa_router


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


class FakeKappaClient:
    def list_clients(self):
        return [{"id": 1, "trade_name": "Lambda Analytics"}]

    def list_projects(self):
        return [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]


def make_app(tmp_path, kappa_client):
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())

    app = FastAPI()
    app.include_router(create_kappa_router(conn, kappa_client))
    return app, conn


def test_get_kappa_clients_returns_list(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/kappa/clients")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "trade_name": "Lambda Analytics"}]


def test_get_kappa_clients_503_when_not_configured(tmp_path):
    app, _ = make_app(tmp_path, None)
    client = TestClient(app)

    response = client.get("/api/kappa/clients")

    assert response.status_code == 503


def test_get_kappa_projects_returns_list(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/kappa/projects")

    assert response.status_code == 200
    assert response.json() == [{"id": 4, "name": "KAPPA", "client_trade_name": "Lambda Analytics"}]


def test_get_groups_lists_discovered_groups_with_mapping(tmp_path):
    app, _ = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.get("/api/groups")

    assert response.status_code == 200
    assert response.json() == [
        {
            "group_id": "1@g.us",
            "name": "Soporte Acme",
            "excluded": False,
            "kappa_client_id": None,
            "kappa_project_id": None,
        }
    ]


def test_put_group_mapping_sets_client_and_project(tmp_path):
    app, conn = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)

    response = client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": 60, "kappa_project_id": 192})

    assert response.status_code == 200
    from monitor.groups import get_group_mapping
    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": 60, "kappa_project_id": 192}


def test_put_group_mapping_clears_with_null(tmp_path):
    app, conn = make_app(tmp_path, FakeKappaClient())
    client = TestClient(app)
    client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": 60, "kappa_project_id": 192})

    response = client.put("/api/groups/1@g.us/mapping", json={"kappa_client_id": None, "kappa_project_id": None})

    assert response.status_code == 200
    from monitor.groups import get_group_mapping
    assert get_group_mapping(conn, "1@g.us") == {"kappa_client_id": None, "kappa_project_id": None}
