from monitor.config import Config
from monitor.llm.anthropic_provider import AnthropicProvider
from monitor.llm.base import LLMProvider

_PROVIDERS = {"anthropic": AnthropicProvider}


def get_provider(config: Config) -> LLMProvider:
    provider_cls = _PROVIDERS.get(config.llm_provider)
    if provider_cls is None:
        raise ValueError(
            f"LLM provider '{config.llm_provider}' is not implemented yet "
            f"(available: {sorted(_PROVIDERS)})"
        )
    return provider_cls(model=config.llm_model, api_key=config.llm_api_key)
