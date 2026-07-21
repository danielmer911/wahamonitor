from datetime import datetime, timezone

from fastapi.testclient import TestClient

from monitor.db import get_connection, init_db
from monitor.groups import exclude_group, sync_groups
from monitor.webhook import create_app


class FakeLLM:
    def __init__(self, response="NO"):
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class FakeWahaClient:
    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


class Config:
    default_inactivity_minutes = 10


def make_app(tmp_path, llm_response="NO"):
    conn = get_connection(str(tmp_path / "monitor.db"), check_same_thread=False)
    init_db(conn)
    sync_groups(conn, FakeWahaClient())
    app = create_app(conn, Config(), FakeLLM(llm_response))
    return app, conn


def waha_payload(message_id="m1", text="Hola, tengo un problema"):
    return {
        "event": "message",
        "payload": {
            "id": message_id,
            "from": "1@g.us",
            "participant": "521555@c.us",
            "participantName": "Juan Perez",
            "body": text,
            "timestamp": 1753099200,
        },
    }


def test_health_check(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_webhook_stores_message_for_known_group(tmp_path):
    app, conn = make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/webhook/waha", json=waha_payload())

    assert response.status_code == 200
    row = conn.execute(
        "SELECT sender_name FROM threads WHERE group_id = ? AND sender_id = ?",
        ("1@g.us", "521555@c.us"),
    ).fetchone()
    assert row[0] == "Juan Perez"


def test_webhook_ignores_excluded_group(tmp_path):
    app, conn = make_app(tmp_path)
    exclude_group(conn, "1@g.us")
    client = TestClient(app)

    response = client.post("/webhook/waha", json=waha_payload())

    assert response.status_code == 200
    row = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE group_id = ?", ("1@g.us",)
    ).fetchone()
    assert row[0] == 0


def test_webhook_deduplicates_repeated_message_id(tmp_path):
    app, conn = make_app(tmp_path)
    client = TestClient(app)

    client.post("/webhook/waha", json=waha_payload(message_id="m1"))
    client.post("/webhook/waha", json=waha_payload(message_id="m1"))

    row = conn.execute(
        "SELECT messages_json FROM threads WHERE group_id = ? AND sender_id = ?",
        ("1@g.us", "521555@c.us"),
    ).fetchone()
    import json
    assert len(json.loads(row[0])) == 1
