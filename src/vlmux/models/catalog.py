"""Data-driven provider presets and persisted custom providers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vlmux.config import default_config_path
from vlmux.exceptions import ConfigurationError

AdapterKind = Literal["openai-compatible", "openrouter", "ollama"]


class ProviderDefinition(BaseModel):
    """Configuration needed to construct one provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1)
    base_url: str | None = Field(default=None, min_length=1)
    adapter: AdapterKind = "openai-compatible"
    requires_api_key: bool = True
    custom: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base URL must not contain embedded credentials")
        return value.rstrip("/")


BUILTIN_PROVIDERS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
    ),
    ProviderDefinition(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        adapter="openrouter",
    ),
    ProviderDefinition(
        id="gemini",
        name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    ),
    ProviderDefinition(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
    ),
    ProviderDefinition(
        id="together",
        name="Together AI",
        base_url="https://api.together.xyz/v1",
    ),
    ProviderDefinition(
        id="fireworks",
        name="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
    ),
    ProviderDefinition(
        id="deepinfra",
        name="DeepInfra",
        base_url="https://api.deepinfra.com/v1/openai",
    ),
    ProviderDefinition(
        id="mistral",
        name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
    ),
    ProviderDefinition(
        id="xai",
        name="xAI",
        base_url="https://api.x.ai/v1",
    ),
    ProviderDefinition(
        id="ollama",
        name="Ollama (local)",
        base_url="http://localhost:11434/v1",
        adapter="ollama",
        requires_api_key=False,
    ),
    ProviderDefinition(
        id="openai-compatible",
        name="Custom endpoint template",
        requires_api_key=False,
    ),
)


def default_provider_catalog_path() -> Path:
    """Return the user-scoped custom provider catalog path."""
    return default_config_path().with_name("providers.json")


class ProviderCatalog:
    """Resolve built-in presets and user-defined OpenAI-compatible providers."""

    def __init__(self, custom: list[ProviderDefinition] | None = None) -> None:
        self._providers = {provider.id: provider for provider in BUILTIN_PROVIDERS}
        for provider in custom or []:
            self._providers[provider.id] = provider

    def providers(self) -> list[ProviderDefinition]:
        return sorted(self._providers.values(), key=lambda provider: provider.id)

    def get(self, provider_id: str) -> ProviderDefinition | None:
        return self._providers.get(provider_id.strip().lower())

    def with_provider(self, provider: ProviderDefinition) -> ProviderCatalog:
        custom = [item for item in self._providers.values() if item.custom]
        custom = [item for item in custom if item.id != provider.id]
        custom.append(provider)
        return ProviderCatalog(custom)


def load_provider_catalog(path: Path | None = None) -> ProviderCatalog:
    """Load custom providers and merge them with built-in presets."""
    catalog_path = path or default_provider_catalog_path()
    if not catalog_path.exists():
        return ProviderCatalog()
    if catalog_path.is_symlink() or not catalog_path.is_file():
        raise ConfigurationError(f"provider catalog path is not a regular file: {catalog_path}")
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        raw_providers = payload["providers"]
        if payload.get("version") != 1 or not isinstance(raw_providers, list):
            raise ValueError("unsupported provider catalog format")
        providers = [ProviderDefinition.model_validate(item) for item in raw_providers]
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as error:
        raise ConfigurationError(f"unable to read provider catalog: {catalog_path}") from error
    if any(not provider.custom for provider in providers):
        raise ConfigurationError("persisted provider definitions must be marked custom")
    return ProviderCatalog(providers)


def save_custom_provider(provider: ProviderDefinition, path: Path | None = None) -> None:
    """Atomically add or replace a custom provider definition."""
    if not provider.custom:
        raise ValueError("only custom providers can be persisted")
    catalog_path = path or default_provider_catalog_path()
    catalog = load_provider_catalog(catalog_path).with_provider(provider)
    custom = [item.model_dump(mode="json") for item in catalog.providers() if item.custom]
    _write_json_atomic(catalog_path, {"version": 1, "providers": custom})


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ConfigurationError(f"refusing to replace symbolic link: {path}")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise ConfigurationError(f"unable to write provider data: {path}") from error
