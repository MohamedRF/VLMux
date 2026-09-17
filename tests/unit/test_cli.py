"""Smoke tests for foundational CLI commands."""

import re
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from vlmux.cli.app import app
from vlmux.config import Settings
from vlmux.core import (
    AgentContext,
    ModelDecision,
    Observation,
    RuntimeResult,
    RuntimeStatus,
    ScreenObservation,
    Task,
)
from vlmux.models import (
    AdapterConfig,
    ModelHealth,
    ProviderCatalog,
    ProviderDefinition,
    VisionSupport,
)
from vlmux.models.base import ModelAdapter
from vlmux.perception import CaptureOptions, ScreenCaptureProvider

runner = CliRunner()
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def normalize_terminal_output(output: str) -> str:
    """Remove styling and wrapping differences from captured terminal output."""
    return " ".join(ANSI_ESCAPE.sub("", output).split())


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "VLMux 0.1.0" in result.stdout


def test_config_show_redacts_api_key(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[model]\napi_key = "super-secret"\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "show", "--config", str(config_file)])

    assert result.exit_code == 0
    assert "super-secret" not in result.stdout
    assert "**********" in result.stdout


def test_invalid_config_returns_nonzero_exit(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("not valid TOML =", encoding="utf-8")

    result = runner.invoke(app, ["config", "show", "--config", str(config_file)])

    assert result.exit_code == 2
    assert "Configuration error" in result.stdout


def test_root_help_lists_only_implemented_commands() -> None:
    result = runner.invoke(app, ["--help"])
    output = normalize_terminal_output(result.stdout)

    assert result.exit_code == 0
    for command in ("doctor", "models", "observe", "run", "screenshot", "version"):
        assert re.search(rf"\b{command}\b", output)


class FakeCaptureProvider(ScreenCaptureProvider):
    def __init__(self) -> None:
        self.options: CaptureOptions | None = None

    async def capture(self, options: CaptureOptions | None = None) -> ScreenObservation:
        self.options = options
        return ScreenObservation(width=1, height=1, image="iVBORw0KGgo=", image_format="png")


def test_screenshot_command_writes_captured_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeCaptureProvider()
    destination = tmp_path / "capture.png"
    monkeypatch.setattr("vlmux.cli.app.create_screen_capture_provider", lambda: provider)
    monkeypatch.setattr("vlmux.cli.app.load_settings", lambda: Settings())

    result = runner.invoke(app, ["screenshot", "--output", str(destination)])

    assert result.exit_code == 0
    assert destination.read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert provider.options is not None
    assert provider.options.max_width == 1440
    assert "Saved 1x1 PNG" in result.stdout


def test_screenshot_refuses_to_replace_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "capture.png"
    destination.write_bytes(b"existing")
    monkeypatch.setattr("vlmux.cli.app.load_settings", lambda: Settings())

    result = runner.invoke(app, ["screenshot", "--output", str(destination)])

    assert result.exit_code == 1
    assert destination.read_bytes() == b"existing"
    assert "use --force" in normalize_terminal_output(result.stdout)


def test_doctor_reports_phase_two_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vlmux.cli.app._probe_screen_capture", lambda: None)
    monkeypatch.setattr("vlmux.cli.app._probe_desktop_control", lambda: None)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "capture succeeded" in result.stdout
    assert "input backend initialized" in result.stdout


def test_doctor_fails_when_capture_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vlmux.cli.app._probe_screen_capture", lambda: "no display")
    monkeypatch.setattr("vlmux.cli.app._probe_desktop_control", lambda: None)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "no display" in result.stdout


def test_observe_redacts_image_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeCaptureProvider()
    monkeypatch.setattr("vlmux.cli.app.create_screen_capture_provider", lambda: provider)
    monkeypatch.setattr("vlmux.cli.app.load_settings", lambda: Settings())

    result = runner.invoke(app, ["observe"])

    assert result.exit_code == 0
    assert "<redacted; use --include-image>" in result.stdout
    assert "iVBORw0KGgo=" not in result.stdout


def test_run_dry_run_prints_proposed_action(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_task(*args: object, **kwargs: object) -> RuntimeResult:
        return RuntimeResult(
            task_id="task",
            status=RuntimeStatus.DRY_RUN,
            steps=1,
            duration_ms=10,
            message="dry run",
        )

    monkeypatch.setattr("vlmux.cli.app.run_task", fake_run_task)
    monkeypatch.setattr(
        "vlmux.cli.app.load_settings",
        lambda **kwargs: Settings(provider="ollama", model="vision"),
    )

    result = runner.invoke(app, ["run", "test task", "--dry-run"])

    assert result.exit_code == 0
    assert "dry_run" in result.stdout


def test_models_list_shows_builtin_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vlmux.cli.app.load_settings",
        lambda: Settings(provider="ollama", model="qwen3-vl"),
    )

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0
    assert "openai-compatible" in result.stdout
    assert "openrouter" in result.stdout
    assert "ollama" in result.stdout


class HealthyAdapter(ModelAdapter):
    def __init__(self) -> None:
        self.closed = False

    async def decide(
        self,
        task: Task,
        observation: Observation,
        context: AgentContext,
    ) -> ModelDecision:
        raise AssertionError("not used")

    async def healthcheck(self) -> ModelHealth:
        return ModelHealth(connected=True, provider="fake", model="vision", detail="connected")

    async def check_image_input(self) -> VisionSupport:
        return VisionSupport(
            accepted=True,
            provider="fake",
            model="vision",
            detail="model accepted an image input",
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeRegistry:
    def __init__(self, adapter: HealthyAdapter) -> None:
        self.adapter = adapter

    def create(self, config: AdapterConfig) -> ModelAdapter:
        self.config = config
        return self.adapter


class RecordingCredentialStore:
    def __init__(self) -> None:
        self.saved: tuple[str, str, str | None] | None = None

    def save_verified(
        self,
        provider: str,
        model: str,
        api_key: SecretStr | None = None,
    ) -> None:
        secret = api_key.get_secret_value() if api_key is not None else None
        self.saved = (provider, model, secret)


def test_models_test_checks_provider_and_closes_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = HealthyAdapter()
    config = AdapterConfig(
        provider="fake",
        model="vision",
        base_url="http://localhost:1",
    )
    monkeypatch.setattr("vlmux.cli.app.load_settings", lambda: Settings())
    monkeypatch.setattr("vlmux.cli.app.resolve_model_reference", lambda *args, **kwargs: config)
    monkeypatch.setattr(
        "vlmux.cli.app.create_builtin_registry", lambda *args: FakeRegistry(adapter)
    )

    result = runner.invoke(app, ["models", "test", "--model", "fake/vision"])

    assert result.exit_code == 0
    assert "accepted an image input" in result.stdout
    assert adapter.closed


def test_models_add_saves_credentials_only_after_image_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = HealthyAdapter()
    registry = FakeRegistry(adapter)
    credentials = RecordingCredentialStore()
    monkeypatch.setenv("TEST_VLMUX_API_KEY", "verified-secret")
    monkeypatch.setattr("vlmux.cli.app.load_provider_catalog", ProviderCatalog)
    monkeypatch.setattr("vlmux.cli.app.create_builtin_registry", lambda *args: registry)
    monkeypatch.setattr("vlmux.cli.app.CredentialStore", lambda: credentials)

    result = runner.invoke(
        app,
        [
            "models",
            "add",
            "--provider",
            "openrouter",
            "--model",
            "vendor/vision",
            "--api-key-env",
            "TEST_VLMUX_API_KEY",
        ],
    )

    assert result.exit_code == 0
    assert credentials.saved == ("openrouter", "vendor/vision", "verified-secret")
    assert registry.config.api_key is not None
    assert "accepted image input" in result.stdout


def test_models_add_persists_custom_provider_after_image_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = HealthyAdapter()
    credentials = RecordingCredentialStore()
    saved: list[ProviderDefinition] = []
    monkeypatch.setenv("TEST_VLMUX_API_KEY", "verified-secret")
    monkeypatch.setattr("vlmux.cli.app.load_provider_catalog", ProviderCatalog)
    monkeypatch.setattr(
        "vlmux.cli.app.create_builtin_registry", lambda *args: FakeRegistry(adapter)
    )
    monkeypatch.setattr("vlmux.cli.app.CredentialStore", lambda: credentials)
    monkeypatch.setattr("vlmux.cli.app.save_custom_provider", saved.append)

    result = runner.invoke(
        app,
        [
            "models",
            "add",
            "--provider",
            "my-vlm",
            "--name",
            "My VLM",
            "--base-url",
            "https://models.example/v1",
            "--model",
            "vision",
            "--api-key-env",
            "TEST_VLMUX_API_KEY",
        ],
    )

    assert result.exit_code == 0
    assert len(saved) == 1
    assert saved[0].id == "my-vlm"
    assert saved[0].custom


def test_models_add_does_not_save_rejected_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class RejectedAdapter(HealthyAdapter):
        async def check_image_input(self) -> VisionSupport:
            return VisionSupport(
                accepted=False,
                provider="openrouter",
                model="text-only",
                detail="image input was rejected",
            )

    credentials = RecordingCredentialStore()
    monkeypatch.setenv("TEST_VLMUX_API_KEY", "unverified-secret")
    monkeypatch.setattr("vlmux.cli.app.load_provider_catalog", ProviderCatalog)
    monkeypatch.setattr(
        "vlmux.cli.app.create_builtin_registry",
        lambda *args: FakeRegistry(RejectedAdapter()),
    )
    monkeypatch.setattr("vlmux.cli.app.CredentialStore", lambda: credentials)

    result = runner.invoke(
        app,
        [
            "models",
            "add",
            "--provider",
            "openrouter",
            "--model",
            "text-only",
            "--api-key-env",
            "TEST_VLMUX_API_KEY",
        ],
    )

    assert result.exit_code == 1
    assert credentials.saved is None
    assert "were not saved" in normalize_terminal_output(result.stdout)
