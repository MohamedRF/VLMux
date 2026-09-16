"""Provider registry and built-in adapter construction."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from vlmux.config import Settings
from vlmux.exceptions import ConfigurationError
from vlmux.models.base import AdapterConfig, ModelAdapter
from vlmux.models.ollama import OllamaAdapter
from vlmux.models.openai_compatible import OpenAICompatibleAdapter
from vlmux.models.openrouter import OpenRouterAdapter

AdapterFactory = Callable[[AdapterConfig], ModelAdapter]
KNOWN_PROVIDERS = ("ollama", "openai", "openai-compatible", "openrouter")
DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class ModelRegistry:
    """Mutable provider registry kept outside the core runtime."""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, provider: str, factory: AdapterFactory) -> None:
        normalized = provider.strip().lower()
        if not normalized:
            raise ValueError("provider name must not be blank")
        self._factories[normalized] = factory

    def providers(self) -> list[str]:
        return sorted(self._factories)

    def create(self, config: AdapterConfig) -> ModelAdapter:
        try:
            factory = self._factories[config.provider]
        except KeyError as error:
            raise ConfigurationError(f"unknown model provider: {config.provider}") from error
        return factory(config)


def create_builtin_registry() -> ModelRegistry:
    """Create a registry containing the Phase 3 providers."""
    registry = ModelRegistry()
    registry.register("openai-compatible", OpenAICompatibleAdapter)
    registry.register("openai", OpenAICompatibleAdapter)
    registry.register("openrouter", OpenRouterAdapter)
    registry.register("ollama", OllamaAdapter)
    return registry


def resolve_model_reference(
    settings: Settings,
    *,
    model_override: str | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
) -> AdapterConfig:
    """Resolve CLI/config model identity without provider branches in runtime code."""
    model_reference = model_override or settings.model
    provider = provider_override or settings.provider
    if model_reference and "/" in model_reference:
        prefix, remainder = model_reference.split("/", 1)
        if prefix in KNOWN_PROVIDERS and (
            provider_override is None or provider_override.lower() == prefix
        ):
            provider = prefix
            model_reference = remainder
    if not model_reference:
        raise ConfigurationError("no model configured; use --model or VLMUX_MODEL")
    if not provider:
        raise ConfigurationError("no provider configured; use --provider or VLMUX_PROVIDER")
    provider = provider.lower()
    base_url = base_url_override or settings.base_url or DEFAULT_BASE_URLS.get(provider)
    if not base_url:
        raise ConfigurationError(f"provider '{provider}' requires --base-url or VLMUX_BASE_URL")
    if settings.offline and not _is_local_url(base_url):
        raise ConfigurationError("offline mode rejects remote model providers")
    if provider in {"openai", "openrouter"} and settings.api_key is None:
        raise ConfigurationError(f"provider '{provider}' requires VLMUX_API_KEY")
    return AdapterConfig(
        provider=provider,
        model=model_reference,
        api_key=settings.api_key,
        base_url=base_url,
        timeout_seconds=settings.model_timeout_seconds,
        request_retries=settings.model_request_retries,
        repair_attempts=settings.model_repair_attempts,
    )


def _is_local_url(value: str) -> bool:
    hostname = urlparse(value).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}
