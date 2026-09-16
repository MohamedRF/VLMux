"""Configuration loading with CLI > environment > file > default precedence."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from vlmux.exceptions import ConfigurationError

ENVIRONMENT_FIELDS = {
    "VLMUX_MODEL": "model",
    "VLMUX_PROVIDER": "provider",
    "VLMUX_API_KEY": "api_key",
    "VLMUX_BASE_URL": "base_url",
    "VLMUX_MAX_STEPS": "max_steps",
    "VLMUX_OFFLINE": "offline",
}

RiskName = Literal["safe", "sensitive", "external_side_effect", "destructive"]


def _default_policy_confirm() -> list[RiskName]:
    return ["sensitive", "destructive"]


class Settings(BaseModel):
    """Validated application configuration without provider-specific coupling."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    api_key: SecretStr | None = None
    base_url: str | None = Field(default=None, min_length=1)
    max_steps: int = Field(default=50, ge=1, le=10_000)
    max_runtime_seconds: float = Field(default=300.0, gt=0, le=86_400)
    max_failures: int = Field(default=3, ge=1, le=100)
    model_repair_attempts: int = Field(default=1, ge=0, le=3)
    model_request_retries: int = Field(default=2, ge=0, le=5)
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    offline: bool = False
    policy_confirm: list[RiskName] = Field(default_factory=_default_policy_confirm)
    policy_deny: list[RiskName] = Field(default_factory=list)
    screenshot_max_width: int | None = Field(default=1440, ge=1)
    screenshot_max_height: int | None = Field(default=1440, ge=1)
    screenshot_format: Literal["png", "jpeg"] = "png"
    screenshot_quality: int = Field(default=85, ge=1, le=100)

    def safe_dict(self) -> dict[str, Any]:
        """Return configuration suitable for logs and terminal output."""
        values = self.model_dump(mode="json")
        if self.api_key is not None:
            values["api_key"] = "**********"
        return values


def default_config_path() -> Path:
    """Return the platform-appropriate user configuration path."""
    return user_config_path("vlmux", appauthor=False) / "config.toml"


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ConfigurationError(f"configuration path is not a file: {path}")
    try:
        with path.open("rb") as config_file:
            document = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"unable to read configuration file: {path}") from error

    allowed_sections = {"model", "runtime", "perception", "policy"}
    unknown_sections = set(document) - allowed_sections
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise ConfigurationError(f"unknown configuration section(s): {names}")

    model = document.get("model", {})
    runtime = document.get("runtime", {})
    perception = document.get("perception", {})
    policy = document.get("policy", {})
    if (
        not isinstance(model, dict)
        or not isinstance(runtime, dict)
        or not isinstance(perception, dict)
        or not isinstance(policy, dict)
    ):
        raise ConfigurationError(
            "model, runtime, perception, and policy configuration must be TOML tables"
        )

    allowed_model = {"name", "provider", "api_key", "base_url"}
    allowed_runtime = {
        "max_steps",
        "max_runtime_seconds",
        "max_failures",
        "model_repair_attempts",
        "model_request_retries",
        "model_timeout_seconds",
        "offline",
    }
    allowed_perception = {"screenshot"}
    allowed_policy = {"confirm", "deny"}
    unknown_model = set(model) - allowed_model
    unknown_runtime = set(runtime) - allowed_runtime
    unknown_perception = set(perception) - allowed_perception
    unknown_policy = set(policy) - allowed_policy
    if unknown_model or unknown_runtime or unknown_perception or unknown_policy:
        option_names = sorted(unknown_model | unknown_runtime | unknown_perception | unknown_policy)
        raise ConfigurationError(f"unknown configuration option(s): {', '.join(option_names)}")

    screenshot = perception.get("screenshot", {})
    if not isinstance(screenshot, dict):
        raise ConfigurationError("perception.screenshot configuration must be a TOML table")
    screenshot_keys = {"max_width", "max_height", "format", "quality"}
    unknown_screenshot = set(screenshot) - screenshot_keys
    if unknown_screenshot:
        raise ConfigurationError(
            f"unknown screenshot option(s): {', '.join(sorted(unknown_screenshot))}"
        )

    values: dict[str, Any] = {}
    if "name" in model:
        values["model"] = model["name"]
    for key in ("provider", "api_key", "base_url"):
        if key in model:
            values[key] = model[key]
    for key in allowed_runtime:
        if key in runtime:
            values[key] = runtime[key]
    for key in screenshot_keys:
        if key in screenshot:
            values[f"screenshot_{key}"] = screenshot[key]
    for key in allowed_policy:
        if key in policy:
            values[f"policy_{key}"] = policy[key]
    return values


def load_settings(
    *,
    cli_overrides: Mapping[str, object | None] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Settings:
    """Load settings according to the documented precedence order."""
    values = _read_config_file(config_path or default_config_path())
    environment = os.environ if environ is None else environ
    for environment_name, field_name in ENVIRONMENT_FIELDS.items():
        if environment_name in environment:
            values[field_name] = environment[environment_name]
    if cli_overrides:
        values.update({key: value for key, value in cli_overrides.items() if value is not None})
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        raise ConfigurationError("configuration validation failed") from error
