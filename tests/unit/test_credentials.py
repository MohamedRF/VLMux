"""API-key persistence and merge behavior for the credential store."""

from __future__ import annotations

import json

from pydantic import SecretStr

from vlmux.models.credentials import CredentialStore


def _store(tmp_path) -> CredentialStore:
    return CredentialStore(path=tmp_path / "auth.json")


def test_save_verified_stores_key_and_verification(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_verified("openrouter", "google/gemini-2.5-pro", SecretStr("sk-123"))

    assert store.api_key("openrouter") is not None
    assert store.api_key("openrouter").get_secret_value() == "sk-123"
    assert store.is_verified("openrouter") is True
    assert store.verified_model("openrouter") == "google/gemini-2.5-pro"


def test_reverify_without_new_key_preserves_stored_key(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_verified("openrouter", "google/gemini-2.5-pro", SecretStr("sk-123"))

    # Re-verify without supplying a key (e.g. provider requires_api_key=False).
    store.save_verified("openrouter", "google/gemini-2.5-pro", None)

    assert store.api_key("openrouter") is not None
    assert store.api_key("openrouter").get_secret_value() == "sk-123"


def test_reverify_with_new_key_replaces_stored_key(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_verified("openrouter", "old-model", SecretStr("sk-123"))

    store.save_verified("openrouter", "new-model", SecretStr("sk-456"))

    assert store.api_key("openrouter").get_secret_value() == "sk-456"
    assert store.verified_model("openrouter") == "new-model"


def test_save_verified_records_image_capability(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_verified("ollama", "qwen3-vl", None)

    payload = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    record = payload["providers"]["ollama"]
    assert record["accepts_image_input"] is True
    assert "verified_at" in record
