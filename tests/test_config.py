import textwrap

import pytest

from monitor.config import load_config


def test_load_config_reads_all_fields(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
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
              db_path: "data/monitor.db"
              tickets_dir: "tickets"
            """
        )
    )

    config = load_config(str(config_path))

    assert config.waha_base_url == "https://waha.example.com"
    assert config.waha_api_key == "waha-key"
    assert config.mcp_url == "https://waha.example.com/mcp"
    assert config.mcp_api_key == "mcp-key"
    assert config.llm_provider == "anthropic"
    assert config.llm_model == "claude-sonnet-5"
    assert config.llm_api_key == "llm-key"
    assert config.default_inactivity_minutes == 10
    assert config.max_thread_lifetime_minutes == 240
    assert config.db_path == "data/monitor.db"
    assert config.tickets_dir == "tickets"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "missing.yaml"))
