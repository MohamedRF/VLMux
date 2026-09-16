"""VLMux developer command-line interface."""

from __future__ import annotations

import asyncio
import base64
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vlmux._version import __version__
from vlmux.cli.services import capture_options_from_settings, run_task
from vlmux.config import default_config_path, load_settings
from vlmux.core import Observation, RuntimeStatus
from vlmux.events import Event, EventBus
from vlmux.exceptions import ConfigurationError, VLMuxError
from vlmux.executors import create_computer_executor
from vlmux.models import ModelHealth, create_builtin_registry, resolve_model_reference
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
    table.add_row("Browser integration", "UNAVAILABLE", "planned for Phase 7")
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
    """List built-in model providers and current configuration."""
    try:
        settings = load_settings()
    except ConfigurationError as error:
        console.print(f"[red]Configuration error:[/red] {error}", style=None)
        raise typer.Exit(code=2) from error
    registry = create_builtin_registry()
    table = Table(title="VLMux model providers")
    table.add_column("Provider")
    table.add_column("Configured")
    table.add_column("Model")
    for provider_name in registry.providers():
        configured = provider_name == settings.provider
        table.add_row(
            provider_name,
            "yes" if configured else "no",
            settings.model if configured and settings.model else "",
        )
    console.print(table)


@models_app.command("test")
def test_model_provider(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model or provider/model reference."),
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
) -> None:
    """Check connectivity to a configured model provider."""
    try:
        settings = load_settings()
        config = resolve_model_reference(
            settings,
            model_override=model,
            provider_override=provider,
            base_url_override=base_url,
        )
        adapter = create_builtin_registry().create(config)

        async def check() -> ModelHealth:
            try:
                return await adapter.healthcheck()
            finally:
                await adapter.aclose()

        health = asyncio.run(check())
    except (VLMuxError, OSError, ValueError) as error:
        console.print(f"[red]Model error:[/red] {error}", style=None)
        raise typer.Exit(code=1) from error
    status = "OK" if health.connected else "ERROR"
    console.print(f"{status}: {health.provider}/{health.model} - {health.detail}")
    if not health.connected:
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


if __name__ == "__main__":
    main()
