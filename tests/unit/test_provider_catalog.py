"""Tests for provider presets, custom definitions, and credential storage."""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from vlmux.config import Settings
from vlmux.models import (
    CredentialStore,
    ProviderCatalog,
    ProviderDefinition,
    load_provider_catalog,
    resolve_model_reference,
    save_custom_provider,
)


def test_builtin_catalog_exposes_common_provider_presets() -> None:
    catalog = ProviderCatalog()

    for provider in ("openai", "openrouter", "gemini", "groq", "ollama"):
        assert catalog.get(provider) is not None


def test_provider_rejects_non_http_url_and_embedded_credentials() -> None:
    with pytest.raises(ValidationError):
        ProviderDefinition(id="bad", name="Bad", base_url="file:///tmp/model", custom=True)
    with pytest.raises(ValidationError):
        ProviderDefinition(
            id="bad",
            name="Bad",
            base_url="https://secret@example.com/v1",
            custom=True,
        )


def test_custom_provider_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "providers.json"
    provider = ProviderDefinition(
        id="acme",
        name="Acme Vision",
        base_url="https://models.example/v1",
        custom=True,
    )

    save_custom_provider(provider, path)

    assert load_provider_catalog(path).get("acme") == provider


def test_verified_credentials_resolve_custom_provider(tmp_path: Path) -> None:
    credentials = CredentialStore(tmp_path / "auth.json")
    credentials.save_verified("acme", "vision-model", SecretStr("secret-key"))
    catalog = ProviderCatalog(
        [
            ProviderDefinition(
                id="acme",
                name="Acme Vision",
                base_url="https://models.example/v1",
                custom=True,
            )
        ]
    )

    config = resolve_model_reference(
        Settings(),
        model_override="acme/vision-model",
        catalog=catalog,
        credentials=credentials,
    )

    assert config.provider == "acme"
    assert config.model == "vision-model"
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "secret-key"
    payload = json.loads(credentials.path.read_text(encoding="utf-8"))
    assert payload["providers"]["acme"]["accepts_image_input"] is True
    assert credentials.verified_model("acme") == "vision-model"
