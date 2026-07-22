import textwrap

from fastapi.testclient import TestClient

from monitor.main import create_full_app


class FakeLLM:
    def generate(self, prompt: str) -> str:
        return "NO"


class FakeWahaClient:
    def __init__(self, base_url=None, api_key=None):
        pass

    def list_groups(self):
        return [{"id": "1@g.us", "name": "Soporte Acme"}]


def test_create_full_app_health_check(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            waha:
              base_url: "https://waha.example.com"
              api_key: "waha-key"
            mcp:
              url: "https://waha.example.com/mcp"
              api_key: "mcp-key"
            llm:
              provider: "anthropic"
              model: "claude-sonnet-5"
              api_key: "llm-key"
            behavior:
              default_inactivity_minutes: 10
              max_thread_lifetime_minutes: 240
            storage:
              db_path: "{tmp_path}/monitor.db"
              tickets_dir: "{tmp_path}/tickets"
            """
        )
    )

    # Mock external services
    monkeypatch.setattr("monitor.main.WahaClient", FakeWahaClient)
    monkeypatch.setattr("monitor.main.get_provider", lambda config: FakeLLM())
    monkeypatch.delenv("MONITOR_DB_PATH", raising=False)

    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_full_app_honors_monitor_db_path_env_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    configured_db_path = tmp_path / "configured.db"
    override_db_path = tmp_path / "override.db"
    config_path.write_text(
        textwrap.dedent(
            f"""
            waha:
              base_url: "https://waha.example.com"
              api_key: "waha-key"
            mcp:
              url: "https://waha.example.com/mcp"
              api_key: "mcp-key"
            llm:
              provider: "anthropic"
              model: "claude-sonnet-5"
              api_key: "llm-key"
            behavior:
              default_inactivity_minutes: 10
              max_thread_lifetime_minutes: 240
            storage:
              db_path: "{configured_db_path}"
              tickets_dir: "{tmp_path}/tickets"
            """
        )
    )

    monkeypatch.setattr("monitor.main.WahaClient", FakeWahaClient)
    monkeypatch.setattr("monitor.main.get_provider", lambda config: FakeLLM())
    monkeypatch.setenv("MONITOR_DB_PATH", str(override_db_path))

    app = create_full_app(str(config_path), start_background_scheduler=False)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert override_db_path.exists()
    assert not configured_db_path.exists()
