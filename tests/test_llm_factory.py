from unittest.mock import MagicMock, patch

import pytest

from monitor.config import Config
from monitor.llm.factory import get_provider
from monitor.llm.anthropic_provider import AnthropicProvider
from monitor.llm.openai_provider import OpenAIProvider


def make_config(provider: str) -> Config:
    return Config(
        waha_base_url="https://waha.example.com",
        waha_api_key="k",
        waha_session="default",
        mcp_url="https://waha.example.com/mcp",
        mcp_api_key=None,
        llm_provider=provider,
        llm_model="claude-sonnet-5",
        llm_api_key="llm-key",
        default_inactivity_minutes=10,
        max_thread_lifetime_minutes=240,
        db_path="data/monitor.db",
        tickets_dir="tickets",
        kappa_base_url=None,
        kappa_api_key=None,
    )


def test_get_provider_returns_anthropic_provider():
    provider = get_provider(make_config("anthropic"))
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_returns_openai_provider():
    provider = get_provider(make_config("openai"))
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_rejects_unimplemented_provider():
    with pytest.raises(ValueError, match="ollama"):
        get_provider(make_config("ollama"))


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


@patch("monitor.llm.openai_provider.OpenAI")
def test_openai_provider_generate_returns_text(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="respuesta generada"))]
    mock_client.chat.completions.create.return_value = mock_response

    provider = OpenAIProvider(model="gpt-4o-mini", api_key="llm-key")
    result = provider.generate("hola")

    assert result == "respuesta generada"
    mock_client.chat.completions.create.assert_called_once()
