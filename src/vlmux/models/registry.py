"""Provider registry and built-in adapter construction."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from vlmux.config import Settings
from vlmux.exceptions import ConfigurationError
from vlmux.models.base import AdapterConfig, ModelAdapter
from vlmux.models.catalog import ProviderCatalog, ProviderDefinition
from vlmux.models.credentials import CredentialStore
from vlmux.models.ollama import OllamaAdapter
from vlmux.models.openai_compatible import OpenAICompatibleAdapter
from vlmux.models.openrouter import OpenRouterAdapter

AdapterFactory = Callable[[AdapterConfig], ModelAdapter]


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


def create_builtin_registry(catalog: ProviderCatalog | None = None) -> ModelRegistry:
    """Create a registry containing presets and configured custom providers."""
    registry = ModelRegistry()
    for provider in (catalog or ProviderCatalog()).providers():
        registry.register(provider.id, _factory_for(provider))
    return registry


def _factory_for(provider: ProviderDefinition) -> AdapterFactory:
    if provider.adapter == "openrouter":
        return OpenRouterAdapter
    if provider.adapter == "ollama":
        return OllamaAdapter
    return OpenAICompatibleAdapter


def resolve_model_reference(
    settings: Settings,
    *,
    model_override: str | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
    catalog: ProviderCatalog | None = None,
    credentials: CredentialStore | None = None,
) -> AdapterConfig:
    """Resolve CLI/config model identity without provider branches in runtime code."""
    provider_catalog = catalog or ProviderCatalog()
    model_reference = model_override or settings.model
    provider = provider_override or settings.provider
    if model_reference and "/" in model_reference:
        prefix, remainder = model_reference.split("/", 1)
        if provider_catalog.get(prefix) is not None and (
            provider_override is None or provider_override.lower() == prefix
        ):
            provider = prefix
            model_reference = remainder
    if not model_reference:
        raise ConfigurationError("no model configured; use --model or VLMUX_MODEL")
    if not provider:
        raise ConfigurationError("no provider configured; use --provider or VLMUX_PROVIDER")
    provider = provider.lower()
    definition = provider_catalog.get(provider)
    if definition is None:
        raise ConfigurationError(
            f"unknown model provider: {provider}; add it with 'vlmux models add'"
        )
    base_url = base_url_override or settings.base_url or definition.base_url
    if not base_url:
        raise ConfigurationError(f"provider '{provider}' requires --base-url or VLMUX_BASE_URL")
    if settings.offline and not _is_local_url(base_url):
        raise ConfigurationError("offline mode rejects remote model providers")
    api_key = settings.api_key or (credentials.api_key(provider) if credentials else None)
    if definition.requires_api_key and api_key is None:
        raise ConfigurationError(
            f"provider '{provider}' requires credentials; use 'vlmux models add' or VLMUX_API_KEY"
        )
    return AdapterConfig(
        provider=provider,
        model=model_reference,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=settings.model_timeout_seconds,
        request_retries=settings.model_request_retries,
        repair_attempts=settings.model_repair_attempts,
    )


def _is_local_url(value: str) -> bool:
    hostname = urlparse(value).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}
