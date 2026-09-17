"""Tests for provider registration and model-reference resolution."""

import pytest

from vlmux.config import Settings
from vlmux.exceptions import ConfigurationError
from vlmux.models import OllamaAdapter, create_builtin_registry, resolve_model_reference


def test_resolves_provider_prefixed_model_reference() -> None:
    config = resolve_model_reference(Settings(), model_override="ollama/qwen3-vl")

    assert config.provider == "ollama"
    assert config.model == "qwen3-vl"
    assert config.base_url == "http://localhost:11434/v1"
    assert isinstance(create_builtin_registry().create(config), OllamaAdapter)


def test_openrouter_model_keeps_nested_model_name() -> None:
    config = resolve_model_reference(
        Settings(api_key="key"),
        model_override="openrouter/google/gemini-model",
    )

    assert config.provider == "openrouter"
    assert config.model == "google/gemini-model"


def test_generic_provider_requires_base_url() -> None:
    with pytest.raises(ConfigurationError, match="requires"):
        resolve_model_reference(
            Settings(provider="openai-compatible", model="model"),
        )


def test_offline_mode_rejects_remote_provider() -> None:
    with pytest.raises(ConfigurationError, match="offline"):
        resolve_model_reference(
            Settings(offline=True),
            model_override="openrouter/model",
        )


def test_remote_builtin_provider_requires_api_key() -> None:
    with pytest.raises(ConfigurationError, match="VLMUX_API_KEY"):
        resolve_model_reference(Settings(), model_override="openrouter/model")


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigurationError, match="unknown"):
        resolve_model_reference(
            Settings(provider="unknown", model="model", base_url="http://localhost:1")
        )
