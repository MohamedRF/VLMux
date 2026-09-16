"""Vision-language model adapter interfaces and built-in providers."""

from vlmux.models.base import AdapterConfig, ModelAdapter, ModelHealth
from vlmux.models.ollama import OllamaAdapter
from vlmux.models.openai_compatible import OpenAICompatibleAdapter
from vlmux.models.openrouter import OpenRouterAdapter
from vlmux.models.registry import ModelRegistry, create_builtin_registry, resolve_model_reference

__all__ = [
    "AdapterConfig",
    "ModelAdapter",
    "ModelHealth",
    "ModelRegistry",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "OpenRouterAdapter",
    "create_builtin_registry",
    "resolve_model_reference",
]
