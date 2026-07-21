from unittest.mock import MagicMock, patch

import pytest

from monitor.config import Config
from monitor.llm.factory import get_provider
from monitor.llm.anthropic_provider import AnthropicProvider


def make_config(provider: str) -> Config:
    return Config(
        waha_base_url="https://waha.example.com",
        waha_api_key="k",
        mcp_url="https://waha.example.com/mcp",
        mcp_api_key=None,
        llm_provider=provider,
        llm_model="claude-sonnet-5",
        llm_api_key="llm-key",
        default_inactivity_minutes=10,
        max_thread_lifetime_minutes=240,
        db_path="data/monitor.db",
        tickets_dir="tickets",
    )


def test_get_provider_returns_anthropic_provider():
    provider = get_provider(make_config("anthropic"))
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_rejects_unimplemented_provider():
    with pytest.raises(ValueError, match="openai"):
        get_provider(make_config("openai"))


@patch("monitor.llm.anthropic_provider.Anthropic")
def test_anthropic_provider_generate_returns_text(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="respuesta generada")]
    mock_client.messages.create.return_value = mock_response

    provider = AnthropicProvider(model="claude-sonnet-5", api_key="llm-key")
    result = provider.generate("hola")

    assert result == "respuesta generada"
    mock_client.messages.create.assert_called_once()
