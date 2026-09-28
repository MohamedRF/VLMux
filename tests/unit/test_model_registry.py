"""Tests for provider registration and model-reference resolution."""

import pytest

from vlmux.config import Settings
from vlmux.exceptions import ConfigurationError
from vlmux.models import (
    AnthropicAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    ProviderCatalog,
    ProviderDefinition,
    create_builtin_registry,
    resolve_model_reference,
)


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


def test_native_anthropic_provider_uses_messages_adapter() -> None:
    config = resolve_model_reference(
        Settings(api_key="key"),
        model_override="anthropic/claude-vision-model",
    )

    assert isinstance(create_builtin_registry().create(config), AnthropicAdapter)


def test_custom_anthropic_provider_uses_messages_adapter() -> None:
    catalog = ProviderCatalog(
        [
            ProviderDefinition(
                id="anthropic-proxy",
                name="Anthropic Proxy",
                base_url="https://models.example",
                adapter="anthropic",
                custom=True,
            )
        ]
    )
    config = resolve_model_reference(
        Settings(api_key="key"),
        model_override="anthropic-proxy/vision-model",
        catalog=catalog,
    )

    assert isinstance(create_builtin_registry(catalog).create(config), AnthropicAdapter)


def test_local_openai_compatible_servers_have_presets() -> None:
    for reference, expected_url in (
        ("vllm/vision-model", "http://localhost:8000/v1"),
        ("llamacpp/vision-model", "http://localhost:8080/v1"),
    ):
        config = resolve_model_reference(Settings(offline=True), model_override=reference)
        assert config.base_url == expected_url
        assert isinstance(create_builtin_registry().create(config), OpenAICompatibleAdapter)


def test_huggingface_disables_optional_json_mode() -> None:
    config = resolve_model_reference(
        Settings(api_key="key"),
        model_override="huggingface/vendor/vision-model",
    )

    assert config.model == "vendor/vision-model"
    assert not config.supports_json_mode


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
