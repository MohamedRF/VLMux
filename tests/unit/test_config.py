"""Tests for centralized configuration loading and redaction."""

from pathlib import Path

import pytest

from vlmux.config import load_settings
from vlmux.exceptions import ConfigurationError


def write_config(path: Path) -> None:
    path.write_text(
        """\
[model]
provider = "file-provider"
name = "file-model"
api_key = "file-secret"
base_url = "http://localhost:1234"

[runtime]
max_steps = 10
max_runtime_seconds = 120
max_failures = 2
model_repair_attempts = 1
model_request_retries = 1
model_timeout_seconds = 30

[perception.screenshot]
max_width = 1280
max_height = 720
format = "jpeg"
quality = 80

[policy]
confirm = ["sensitive"]
deny = ["destructive"]
""",
        encoding="utf-8",
    )


def test_precedence_is_cli_then_environment_then_file_then_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    settings = load_settings(
        config_path=config_path,
        environ={
            "VLMUX_PROVIDER": "environment-provider",
            "VLMUX_MODEL": "environment-model",
            "VLMUX_MAX_STEPS": "20",
        },
        cli_overrides={"model": "cli-model", "max_steps": 30},
    )

    assert settings.provider == "environment-provider"
    assert settings.model == "cli-model"
    assert settings.max_steps == 30
    assert settings.base_url == "http://localhost:1234"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "file-secret"
    assert settings.screenshot_max_width == 1280
    assert settings.screenshot_max_height == 720
    assert settings.screenshot_format == "jpeg"
    assert settings.screenshot_quality == 80
    assert settings.max_runtime_seconds == 120
    assert settings.max_failures == 2
    assert settings.model_request_retries == 1
    assert settings.policy_confirm == ["sensitive"]
    assert settings.policy_deny == ["destructive"]


def test_defaults_are_used_when_sources_are_empty(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.toml", environ={})

    assert settings.model is None
    assert settings.provider is None
    assert settings.max_steps == 50
    assert settings.screenshot_max_width == 1440
    assert settings.screenshot_format == "png"
    assert settings.max_runtime_seconds == 300


def test_safe_output_never_contains_secret(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    safe_output = str(load_settings(config_path=config_path, environ={}).safe_dict())

    assert "file-secret" not in safe_output
    assert "**********" in safe_output


def test_invalid_environment_value_becomes_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="validation failed"):
        load_settings(
            config_path=tmp_path / "missing.toml",
            environ={"VLMUX_MAX_STEPS": "not-an-integer"},
        )


def test_unknown_configuration_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[runtime]\nmax_retries = 3\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="max_retries"):
        load_settings(config_path=config_path, environ={})


def test_invalid_screenshot_configuration_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[perception.screenshot]\nformat = "webp"\nquality = 101\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="validation failed"):
        load_settings(config_path=config_path, environ={})


def test_offline_environment_value_is_parsed(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        environ={"VLMUX_OFFLINE": "true"},
    )

    assert settings.offline is True
