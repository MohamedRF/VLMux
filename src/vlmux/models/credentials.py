"""User-scoped provider credential persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from vlmux.config import default_config_path
from vlmux.exceptions import ConfigurationError
from vlmux.models.catalog import _write_json_atomic


def default_credentials_path() -> Path:
    """Return the credentials path, separate from ordinary configuration."""
    return default_config_path().with_name("auth.json")


class CredentialStore:
    """Read and write API keys without exposing them through settings output."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_credentials_path()

    def api_key(self, provider: str) -> SecretStr | None:
        record = self._records().get(provider)
        if not isinstance(record, dict) or not isinstance(record.get("api_key"), str):
            return None
        return SecretStr(record["api_key"])

    def verified_model(self, provider: str) -> str | None:
        record = self._records().get(provider)
        value = record.get("verified_model") if isinstance(record, dict) else None
        return value if isinstance(value, str) else None

    def has(self, provider: str) -> bool:
        return self.api_key(provider) is not None

    def is_verified(self, provider: str) -> bool:
        record = self._records().get(provider)
        return isinstance(record, dict) and record.get("accepts_image_input") is True

    def save_verified(
        self,
        provider: str,
        model: str,
        api_key: SecretStr | None = None,
    ) -> None:
        records = self._records()
        record: dict[str, object] = {
            "verified_model": model,
            "accepts_image_input": True,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        if api_key is not None:
            record["api_key"] = api_key.get_secret_value()
        records[provider] = record
        _write_json_atomic(self.path, {"version": 1, "providers": records})

    def _records(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or not self.path.is_file():
            raise ConfigurationError(f"credentials path is not a regular file: {self.path}")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ConfigurationError(f"unable to read credentials: {self.path}") from error
        if not isinstance(payload, dict):
            raise ConfigurationError(f"unsupported credentials format: {self.path}")
        providers = payload.get("providers")
        if payload.get("version") != 1 or not isinstance(providers, dict):
            raise ConfigurationError(f"unsupported credentials format: {self.path}")
        return providers
