"""VLMux developer command-line interface."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import SecretStr, ValidationError
from rich.console import Console
from rich.table import Table

from vlmux._version import __version__
from vlmux.cli.services import capture_options_from_settings, run_task
from vlmux.config import default_config_path, load_settings
from vlmux.core import Observation, RuntimeStatus
from vlmux.events import Event, EventBus
from vlmux.exceptions import ConfigurationError, UnsupportedPlatformError, VLMuxError
from vlmux.executors import create_computer_executor
from vlmux.models import (
    AdapterConfig,
    CredentialStore,
    ProviderDefinition,
    VisionSupport,
    create_builtin_registry,
    load_provider_catalog,
    resolve_model_reference,
    save_custom_provider,
)
from vlmux.perception import CaptureOptions, create_screen_capture_provider
from vlmux.policy import PolicyDecision
from vlmux.protocol import Action, dump_action_json

app = typer.Typer(
    name="vlmux",
    help="Give any vision-language model a computer.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Inspect VLMux configuration.", no_args_is_help=True)
models_app = typer.Typer(help="Inspect and test configured model providers.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
console = Console()


@app.command()
def version() -> None:
    """Show the installed VLMux version."""
    console.print(f"VLMux {__version__}")


@app.command()
def doctor() -> None:
    """Report foundational runtime and feature availability."""
    table = Table(title="VLMux doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    python_supported = sys.version_info >= (3, 12)
    table.add_row(
        "VLMux",
        "OK",
        __version__,
    )
    table.add_row(
        "Python",
        "OK" if python_supported else "ERROR",
        platform.python_version(),
    )
    table.add_row("Operating system", "INFO", platform.platform())
    try:
        settings = load_settings()
    except ConfigurationError as error:
        table.add_row("Configuration", "ERROR", str(error))
    else:
        configured_model = (
            f"{settings.provider}/{settings.model}"
            if settings.provider and settings.model
            else "not configured"
        )
        table.add_row("Configuration", "OK", str(default_config_path()))
        table.add_row("Model", "INFO", configured_model)
    capture_error = _probe_screen_capture()
    table.add_row(
        "Screen capture",
        "OK" if capture_error is None else "ERROR",
        capture_error or "capture succeeded",
    )
    executor_error = _probe_desktop_control()
    table.add_row(
        "Desktop control",
        "OK" if executor_error is None else "ERROR",
        executor_error or "input backend initialized",
    )
    browser_available, browser_detail = _probe_browser()
    table.add_row(
        "Browser integration", "OK" if browser_available else "UNAVAILABLE", browser_detail
    )
    ui_ok, ui_detail = _probe_ui_tree()
    table.add_row("Accessibility tree", "OK" if ui_ok else "UNAVAILABLE", ui_detail)
    console.print(table)
    if not python_supported or capture_error is not None or executor_error is not None:
        raise typer.Exit(code=1)


def _probe_screen_capture() -> str | None:
    try:
        provider = create_screen_capture_provider()
        asyncio.run(provider.capture(CaptureOptions(max_width=1, max_height=1)))
    except (VLMuxError, OSError) as error:
        return str(error)
    return None


def _probe_desktop_control() -> str | None:
    try:
        create_computer_executor()
    except (VLMuxError, OSError) as error:
        return str(error)
    return None


def _probe_browser() -> tuple[bool, str]:
    try:
        settings = load_settings()
    except ConfigurationError:
        return False, "not configured"
    if not settings.browser_cdp_url:
        return False, "no CDP endpoint configured (set browser_cdp_url)"
    return True, settings.browser_cdp_url


def _probe_ui_tree() -> tuple[bool, str]:
    try:
        from vlmux.perception.ui_tree import RefRegistry
        from vlmux.perception.windows_uia import WindowsUITreeProvider

        provider = WindowsUITreeProvider(RefRegistry())
        snapshot = provider.snapshot(max_elements=1)
        return True, f"desktop visible ({snapshot.to_dict()['ref_count']}+ interactive refs)"
    except UnsupportedPlatformError as error:
        return False, str(error)
    except Exception as error:
        return False, str(error)


def _emit_envelope(
    ok: bool, command: str, *, data: Any = None, error: str | None = None, code: str | None = None
) -> None:
    """Print one machine-readable JSON envelope (agent-desktop style)."""
    payload: dict[str, Any] = {
        "version": __version__,
        "ok": ok,
        "command": command,
    }
    if data is not None:
        payload["data"] = data
    if error is not None:
        payload["error"] = {"message": error, "code": code}
    print(json.dumps(payload))


def _ui_tree_cli() -> Any:
    """Build a UIA provider persisting snapshots in the user cache directory."""
    from platformdirs import user_cache_path

    from vlmux.perception.ui_tree import RefRegistry
    from vlmux.perception.windows_uia import WindowsUITreeProvider

    registry = RefRegistry(cache_dir=user_cache_path("vlmux", appauthor=False) / "snapshots")
    provider = WindowsUITreeProvider(registry)
    return provider, registry


@app.command("snapshot")
def snapshot_command(
    window_id: Annotated[
        str | None,
        typer.Option("--window-id", help="Capture only this window handle."),
    ] = None,
    app: Annotated[
        str | None,
        typer.Option("--app", help="Capture only the window whose title contains this text."),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive/--all", "-i", help="Only elements an agent can act on."),
    ] = True,
    max_elements: Annotated[int, typer.Option("--max-elements", min=1, max=2000)] = 500,
) -> None:
    """Print the accessibility tree with element refs as a JSON envelope.

    Refs look like ``@s1a2b3:e8`` and belong to this snapshot; pass them to
    ``vlmux click`` or ``vlmux set-value``. Re-snapshot when a ref action
    fails with code ``stale_ref``.
    """
    try:
        provider, _registry = _ui_tree_cli()
        snapshot = provider.snapshot(
            window_id=window_id,
            app=app,
            interactive_only=interactive,
            max_elements=max_elements,
        )
    except VLMuxError as error:
        _emit_envelope(False, "snapshot", error=str(error), code=getattr(error, "code", "error"))
        raise typer.Exit(code=1) from error
    _emit_envelope(True, "snapshot", data=snapshot.to_dict())


@app.command("click")
def click_command(
    ref: Annotated[str, typer.Argument(help="Element ref, e.g. '@s1a2b3:e8'.")],
    button: Annotated[str, typer.Option("--button", help="Mouse button.")] = "left",
    double: Annotated[bool, typer.Option("--double", help="Double-invoke.")] = False,
) -> None:
    """Invoke an accessibility-tree element by ref (headless, no pointer)."""
    from vlmux.protocol import ClickRefAction

    if button not in {"left", "middle", "right"}:
        _emit_envelope(False, "click", error=f"invalid button: {button!r}", code="invalid_args")
        raise typer.Exit(code=2)
    try:
        provider, registry = _ui_tree_cli()
        executor = create_computer_executor(ui_registry=registry, ui_provider=provider)
        action = ClickRefAction(
            ref=ref,
            button=button,  # narrowed by the explicit check above
            clicks=2 if double else 1,
        )
        result = asyncio.run(executor.execute(action))
    except (VLMuxError, ValueError) as error:
        _emit_envelope(
            False,
            "click",
            error=str(error),
            code=getattr(error, "code", "invalid_args"),
        )
        raise typer.Exit(code=1) from error
    payload = result.model_dump(mode="json")
    payload.pop("id", None)
    if result.success:
        payload.pop("error", None)
        _emit_envelope(True, "click", data=payload)
        return
    _emit_envelope(
        False,
        "click",
        data=payload,
        error=result.error or "action failed",
        code=result.error_code or "action_execution_error",
    )
    raise typer.Exit(code=1)


@app.command("set-value")
def set_value_command(
    ref: Annotated[str, typer.Argument(help="Element ref, e.g. '@s1a2b3:e8'.")],
    value: Annotated[str | None, typer.Argument(help="Value to set (omit with --stdin).")] = None,
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read the value from stdin (keeps secrets out of ps output)."),
    ] = False,
) -> None:
    """Set an accessibility-tree element's value by ref (headless)."""
    from vlmux.protocol import SetValueRefAction

    if stdin == (value is not None):
        console.print("[red]Pass exactly one of VALUE or --stdin.[/red]")
        raise typer.Exit(code=2)
    resolved = sys.stdin.read() if stdin else str(value)
    try:
        provider, registry = _ui_tree_cli()
        executor = create_computer_executor(ui_registry=registry, ui_provider=provider)
        action = SetValueRefAction(ref=ref, value=resolved)
        result = asyncio.run(executor.execute(action))
    except (VLMuxError, ValueError) as error:
        _emit_envelope(
            False,
            "set-value",
            error=str(error),
            code=getattr(error, "code", "invalid_args"),
        )
        raise typer.Exit(code=1) from error
    if result.success:
        _emit_envelope(True, "set-value", data={"ok": True})
        return
    _emit_envelope(
        False,
        "set-value",
        error=result.error or "action failed",
        code=result.error_code or "action_execution_error",
    )
    raise typer.Exit(code=1)


@app.command("observe")
def observe(
    include_image: Annotated[
        bool,
        typer.Option("--include-image", help="Include screenshot base64 in JSON output."),
    ] = False,
) -> None:
    """Capture and print one RAW observation without contacting a model."""
    try:
        settings = load_settings()
        screen = asyncio.run(
            create_screen_capture_provider().capture(capture_options_from_settings(settings))
        )
        observation = Observation(screen=screen)
        payload = observation.model_dump(mode="json")
        if not include_image:
            screen_payload = payload["screen"]
            if isinstance(screen_payload, dict):
                screen_payload["image"] = "<redacted; use --include-image>"
    except (VLMuxError, OSError, ValueError) as error:
        console.print(f"[red]Observation error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error
    console.print_json(data=payload)


@app.command("run")
def run_command(
    instruction: Annotated[str, typer.Argument(help="Computer-use task to perform.")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model or provider/model reference."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Override the configured provider."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="Override the provider API base URL."),
    ] = None,
    max_steps: Annotated[
        int | None,
        typer.Option("--max-steps", help="Override the configured step limit."),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override the maximum task runtime in seconds."),
    ] = None,
    max_failures: Annotated[
        int | None,
        typer.Option("--max-failures", help="Override the consecutive failure limit."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Propose one validated action without executing it."),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Reject non-local model provider URLs."),
    ] = False,
    assume_yes: Annotated[
        bool,
        typer.Option("--yes", help="Approve policy confirmation prompts automatically."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Print runtime events."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Re-raise errors with developer traceback output."),
    ] = False,
) -> None:
    """Run a bounded computer-use task through the configured vision model."""
    try:
        settings = load_settings(
            cli_overrides={
                "model": model,
                "provider": provider,
                "base_url": base_url,
                "max_steps": max_steps,
                "max_runtime_seconds": timeout,
                "max_failures": max_failures,
                "offline": True if offline else None,
            }
        )
        events = EventBus()
        if verbose:
            events.subscribe(_print_event)

        async def confirm(action: Action, decision: PolicyDecision) -> bool:
            console.print(f"Policy: {decision.reason}")
            console.print_json(dump_action_json(action))
            return assume_yes or typer.confirm("Approve this action?")

        result = asyncio.run(
            run_task(
                instruction,
                settings,
                dry_run=dry_run,
                confirmation_handler=confirm,
                events=events,
            )
        )
    except (VLMuxError, OSError, ValueError) as error:
        if debug:
            raise
        console.print(f"[red]Run error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error

    table = Table(title="VLMux result")
    table.add_column("Status")
    table.add_column("Steps", justify="right")
    table.add_column("Duration")
    table.add_column("Message")
    table.add_row(
        result.status.value,
        str(result.steps),
        f"{result.duration_ms / 1000:.2f}s",
        result.message or "",
    )
    console.print(table)
    if result.final_action is not None:
        console.print_json(dump_action_json(result.final_action))
    if result.status not in {RuntimeStatus.SUCCEEDED, RuntimeStatus.DRY_RUN}:
        raise typer.Exit(code=1)


def _print_event(event: Event) -> None:
    console.print(f"[dim]{event.name}[/dim]")


@models_app.command("list")
def list_model_providers() -> None:
    """List provider presets, custom providers, and verification status."""
    try:
        settings = load_settings()
        catalog = load_provider_catalog()
        credentials = CredentialStore()
        rows = [
            (
                definition,
                credentials.verified_model(definition.id) or "",
            )
            for definition in catalog.providers()
        ]
    except ConfigurationError as error:
        console.print(f"[red]Configuration error:[/red] {error}", style=None)
        raise typer.Exit(code=2) from error
    table = Table(title="VLMux model providers")
    table.add_column("Provider", no_wrap=True)
    table.add_column("Type")
    table.add_column("Protocol")
    table.add_column("Configured")
    table.add_column("Vision-verified model")
    for definition, verified_model in rows:
        configured = definition.id == settings.provider
        table.add_row(
            definition.id,
            "custom" if definition.custom else "preset",
            definition.adapter,
            "yes" if configured else "no",
            verified_model,
        )
    console.print(table)


@models_app.command("add")
def add_model_provider(
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Preset or new custom provider ID."),
    ],
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Exact model ID exposed by the provider."),
    ],
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="API base URL for a custom provider."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Display name for a custom provider."),
    ] = None,
    protocol: Annotated[
        str,
        typer.Option(
            "--protocol",
            help="Custom provider protocol: openai-compatible or anthropic.",
        ),
    ] = "openai-compatible",
    no_json_mode: Annotated[
        bool,
        typer.Option(
            "--no-json-mode",
            help="Do not send OpenAI response_format (for incompatible endpoints/models).",
        ),
    ] = False,
    api_key_env: Annotated[
        str | None,
        typer.Option(
            "--api-key-env",
            help="Read the API key from this environment variable instead of prompting.",
        ),
    ] = None,
    no_api_key: Annotated[
        bool,
        typer.Option("--no-api-key", help="Custom/local endpoint does not require a key."),
    ] = False,
) -> None:
    """Verify a model accepts images, then save its provider credentials."""
    provider_id = provider.strip().lower()
    model_id = model.strip()
    try:
        if not model_id:
            raise ConfigurationError("model ID must not be blank")
        catalog = load_provider_catalog()
        definition = catalog.get(provider_id)
        is_custom = definition is None or provider_id == "openai-compatible"
        if is_custom:
            if not base_url:
                raise ConfigurationError("a custom provider requires --base-url")
            if protocol not in {"openai-compatible", "anthropic"}:
                raise ConfigurationError(
                    "custom provider protocol must be 'openai-compatible' or 'anthropic'"
                )
            if protocol == "anthropic" and no_json_mode:
                raise ConfigurationError("--no-json-mode applies only to openai-compatible APIs")
            definition = ProviderDefinition(
                id=provider_id,
                name=name or provider_id,
                base_url=base_url,
                adapter=protocol,
                requires_api_key=not no_api_key,
                supports_json_mode=not no_json_mode,
                custom=True,
            )
            catalog = catalog.with_provider(definition)
        elif (
            base_url is not None
            or name is not None
            or no_api_key
            or protocol != "openai-compatible"
            or no_json_mode
        ):
            raise ConfigurationError(
                "preset providers cannot be overridden; use a new custom provider ID"
            )
        if definition is None or definition.base_url is None:
            raise ConfigurationError("provider does not define an API base URL")

        api_key: SecretStr | None = None
        if definition.requires_api_key:
            raw_api_key = os.environ.get(api_key_env) if api_key_env else None
            if api_key_env and raw_api_key is None:
                raise ConfigurationError(f"environment variable is not set: {api_key_env}")
            if raw_api_key is None:
                raw_api_key = typer.prompt("API key", hide_input=True)
            if not raw_api_key.strip():
                raise ConfigurationError("API key must not be blank")
            api_key = SecretStr(raw_api_key)

        config = AdapterConfig(
            provider=definition.id,
            model=model_id,
            api_key=api_key,
            base_url=definition.base_url,
            supports_json_mode=definition.supports_json_mode,
        )
        adapter = create_builtin_registry(catalog).create(config)

        async def verify() -> VisionSupport:
            try:
                return await adapter.check_image_input()
            finally:
                await adapter.aclose()

        support = asyncio.run(verify())
        if not support.accepted:
            raise ConfigurationError(
                f"credentials were not saved because {support.provider}/{support.model} "
                f"did not pass image-input validation: {support.detail}"
            )
        if definition.custom:
            save_custom_provider(definition)
        CredentialStore().save_verified(definition.id, model_id, api_key)
    except (VLMuxError, OSError, ValueError, ValidationError) as error:
        console.print(f"[red]Model setup error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error
    saved_item = "credentials" if api_key is not None else "provider verification"
    console.print(f"OK: {definition.id}/{model_id} accepted image input; {saved_item} saved.")


@models_app.command("test")
def test_model_provider(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model or provider/model reference."),
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
) -> None:
    """Verify that a configured model can interpret image input."""
    try:
        settings = load_settings()
        catalog = load_provider_catalog()
        config = resolve_model_reference(
            settings,
            model_override=model,
            provider_override=provider,
            base_url_override=base_url,
            catalog=catalog,
            credentials=CredentialStore(),
        )
        adapter = create_builtin_registry(catalog).create(config)

        async def check() -> VisionSupport:
            try:
                return await adapter.check_image_input()
            finally:
                await adapter.aclose()

        support = asyncio.run(check())
    except (VLMuxError, OSError, ValueError) as error:
        console.print(f"[red]Model error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error
    status = "OK" if support.accepted else "ERROR"
    console.print(f"{status}: {support.provider}/{support.model} - {support.detail}")
    if not support.accepted:
        raise typer.Exit(code=1)


@app.command()
def screenshot(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination image path."),
    ] = None,
    monitor: Annotated[
        int | None,
        typer.Option(help="MSS monitor index; 0 captures the virtual desktop."),
    ] = None,
    active_window: Annotated[
        bool,
        typer.Option("--active-window", help="Capture only the foreground window."),
    ] = False,
    max_width: Annotated[
        int | None,
        typer.Option(help="Maximum encoded width while preserving aspect ratio."),
    ] = None,
    max_height: Annotated[
        int | None,
        typer.Option(help="Maximum encoded height while preserving aspect ratio."),
    ] = None,
    image_format: Annotated[
        str | None,
        typer.Option("--format", help="Image format: png or jpeg."),
    ] = None,
    quality: Annotated[
        int | None,
        typer.Option(help="JPEG quality from 1 through 100."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing destination file."),
    ] = False,
) -> None:
    """Capture the screen and write an encoded image file."""
    try:
        settings = load_settings()
        options = CaptureOptions(
            monitor=monitor,
            active_window=active_window,
            max_width=max_width if max_width is not None else settings.screenshot_max_width,
            max_height=max_height if max_height is not None else settings.screenshot_max_height,
            image_format=image_format or settings.screenshot_format,
            quality=quality if quality is not None else settings.screenshot_quality,
        )
        destination = output or Path(f"vlmux-screenshot.{options.image_format}")
        if destination.exists() and not force:
            raise VLMuxError(
                f"destination already exists: {destination}; use --force to replace it"
            )
        observation = asyncio.run(create_screen_capture_provider().capture(options))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(observation.image, validate=True))
    except (VLMuxError, OSError, ValueError) as error:
        console.print(f"[red]Screenshot error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error
    console.print(
        f"Saved {observation.width}x{observation.height} {observation.image_format.upper()} "
        f"screenshot to {destination}"
    )


@config_app.command("show")
def show_config(
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Read a specific TOML configuration file."),
    ] = None,
) -> None:
    """Show effective configuration with secrets redacted."""
    try:
        settings = load_settings(config_path=config_file)
    except ConfigurationError as error:
        console.print(f"[red]Configuration error:[/red] {error}", style=None)
        raise typer.Exit(code=2) from error
    console.print_json(data=settings.safe_dict())


@config_app.command("path")
def show_config_path() -> None:
    """Show the default configuration file path."""
    console.print(str(default_config_path()))


def main() -> None:
    """Run the VLMux CLI."""
    app()


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.", min=1, max=65535)] = 8765,
    token: Annotated[
        str | None,
        typer.Option(
            help="Require 'Authorization: Bearer <token>' on all requests. "
            "Defaults to the VLMUX_API_TOKEN environment variable. "
            "Always required for non-loopback hosts."
        ),
    ] = None,
) -> None:
    """Start the local REST API exposing the VLMux runtime."""
    from vlmux.server import serve as serve_api

    try:
        serve_api(host=host, port=port, token=token)
    except ValueError as error:
        console.print(f"[red]Cannot start server:[/red] {error}")
        raise typer.Exit(code=2) from error


@app.command()
def mcp() -> None:
    """Start the MCP server over stdio (also available as vlmux-mcp)."""
    from vlmux.mcp.server import main as mcp_main

    mcp_main()


@app.command()
def replay(
    run_id: Annotated[str, typer.Argument(help="Run directory under runs/.")],
    runs_dir: Annotated[str, typer.Option(help="Runs directory.")] = "runs",
) -> None:
    """Display a recorded task trace."""
    import re

    from vlmux.trace import load_trace_events, load_trace_steps

    if not re.fullmatch(r"[\w][\w.-]{0,127}", run_id):
        console.print(
            f"[red]Invalid run id:[/red] {run_id!r} (expected letters, digits, '-' or '_')"
        )
        raise typer.Exit(code=1)
    directory = Path(runs_dir) / run_id
    if not directory.exists():
        console.print(f"[red]Trace not found:[/red] {directory}")
        raise typer.Exit(code=1)
    task_path = directory / "task.json"
    if task_path.exists():
        try:
            console.print_json(data=json.loads(task_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            console.print(f"[red]task.json is corrupt:[/red] {error}")
            raise typer.Exit(code=1) from error
    steps = load_trace_steps(directory)
    events = load_trace_events(directory)
    table = Table(title=f"Replay: {run_id}")
    table.add_column("Step", justify="right")
    table.add_column("Action")
    table.add_column("Success")
    for step in steps:
        decision = step.get("decision", {})
        result = step.get("result") or {}
        action = decision.get("action", {}) if isinstance(decision, dict) else {}
        table.add_row(
            str(step.get("step")),
            str(action.get("type", "?")),
            str(result.get("success", "")),
        )
    console.print(table)
    console.print(f"{len(events)} events recorded.")
    console.print(f"Screenshots: {len(list((directory / 'screenshots').glob('*')))} files.")


@app.command()
def benchmark(
    directory: Annotated[str, typer.Argument(help="Directory containing benchmark TOML specs.")],
    models: Annotated[
        list[str] | None, typer.Option("--model", help="Model reference to evaluate.")
    ] = None,
) -> None:
    """Run benchmark specs against one or more models."""
    from vlmux.benchmark import BenchmarkRunner, discover_specs, format_report
    from vlmux.benchmark.runner import BenchmarkResult

    model_refs: list[str] = list(models) if models else []
    try:
        settings = load_settings()
    except ConfigurationError:
        settings = None
    if not model_refs:
        if settings is None or not settings.provider or not settings.model:
            console.print(
                "[red]No model configured.[/red] "
                "Pass --model provider/model or run `vlmux config show`."
            )
            raise typer.Exit(code=1)
        model_refs = [f"{settings.provider}/{settings.model}"]

    async def run_task_for_benchmark(task_text: str, model_ref: str, max_steps: int) -> object:
        benchmark_settings = load_settings(
            cli_overrides={"max_steps": max_steps},
        )
        return await run_task(task_text, benchmark_settings, model_override=model_ref)

    try:
        specs = discover_specs(directory)
    except FileNotFoundError as error:
        console.print(f"[red]Benchmark error:[/red] {error}")
        raise typer.Exit(code=1) from error
    except (OSError, ValueError) as error:
        console.print(f"[red]Benchmark error:[/red] {error}")
        raise typer.Exit(code=1) from error
    if not specs:
        console.print("No benchmark specs found.")
        raise typer.Exit(code=1)

    async def run_all() -> list[BenchmarkResult]:
        runner = BenchmarkRunner(run_task_for_benchmark)
        results: list[BenchmarkResult] = []
        price_input = settings.input_price_per_1k if settings else None
        price_output = settings.output_price_per_1k if settings else None
        for spec in specs:
            for model_ref in model_refs:
                try:
                    results.append(
                        await runner.run_one(
                            spec,
                            model_ref,
                            input_price_per_1k=price_input,
                            output_price_per_1k=price_output,
                        )
                    )
                except Exception as error:
                    console.print(
                        f"[red]Benchmark error[/red] spec={spec.name} model={model_ref}: {error}"
                    )
                    results.append(
                        BenchmarkResult(
                            spec_name=spec.name,
                            model=model_ref,
                            success=False,
                            steps=0,
                            latency_ms=0.0,
                            input_tokens=0,
                            output_tokens=0,
                            cost="unknown",
                            status="error",
                        )
                    )
        return results

    console.print(format_report(asyncio.run(run_all())))


if __name__ == "__main__":
    main()
