"""Vision-language model adapter interfaces and built-in providers."""

from vlmux.models.base import AdapterConfig, ModelAdapter, ModelHealth, VisionSupport
from vlmux.models.catalog import (
    ProviderCatalog,
    ProviderDefinition,
    default_provider_catalog_path,
    load_provider_catalog,
    save_custom_provider,
)
from vlmux.models.credentials import CredentialStore, default_credentials_path
from vlmux.models.ollama import OllamaAdapter
from vlmux.models.openai_compatible import OpenAICompatibleAdapter
from vlmux.models.openrouter import OpenRouterAdapter
from vlmux.models.registry import ModelRegistry, create_builtin_registry, resolve_model_reference

__all__ = [
    "AdapterConfig",
    "CredentialStore",
    "ModelAdapter",
    "ModelHealth",
    "ModelRegistry",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "OpenRouterAdapter",
    "ProviderCatalog",
    "ProviderDefinition",
    "VisionSupport",
    "create_builtin_registry",
    "default_credentials_path",
    "default_provider_catalog_path",
    "load_provider_catalog",
    "resolve_model_reference",
    "save_custom_provider",
]
