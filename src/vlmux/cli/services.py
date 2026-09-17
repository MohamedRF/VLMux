"""Composition root shared by Phase 5 CLI commands."""

from __future__ import annotations

from vlmux.config import Settings
from vlmux.core import RuntimeResult
from vlmux.events import EventBus
from vlmux.executors import create_computer_executor
from vlmux.models import (
    CredentialStore,
    create_builtin_registry,
    load_provider_catalog,
    resolve_model_reference,
)
from vlmux.observation import ScreenObserver
from vlmux.perception import CaptureOptions, create_screen_capture_provider
from vlmux.policy import PolicyEngine, RiskLevel
from vlmux.runtime import ConfirmationHandler, Runtime, RuntimeConfig


def capture_options_from_settings(settings: Settings) -> CaptureOptions:
    """Translate central settings into perception options."""
    return CaptureOptions(
        max_width=settings.screenshot_max_width,
        max_height=settings.screenshot_max_height,
        image_format=settings.screenshot_format,
        quality=settings.screenshot_quality,
    )


async def run_task(
    instruction: str,
    settings: Settings,
    *,
    model_override: str | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
    max_steps_override: int | None = None,
    dry_run: bool = False,
    confirmation_handler: ConfirmationHandler | None = None,
    events: EventBus | None = None,
) -> RuntimeResult:
    """Construct and run one task, always closing owned network resources."""
    catalog = load_provider_catalog()
    adapter_config = resolve_model_reference(
        settings,
        model_override=model_override,
        provider_override=provider_override,
        base_url_override=base_url_override,
        catalog=catalog,
        credentials=CredentialStore(),
    )
    adapter = create_builtin_registry(catalog).create(adapter_config)
    observer = ScreenObserver(
        create_screen_capture_provider(),
        capture_options_from_settings(settings),
    )
    executor = None if dry_run else create_computer_executor()
    runtime = Runtime(
        model=adapter,
        observer=observer,
        executor=executor,
        policy=PolicyEngine(
            confirm={RiskLevel(value) for value in settings.policy_confirm},
            deny={RiskLevel(value) for value in settings.policy_deny},
        ),
        events=events,
        confirmation_handler=confirmation_handler,
        config=RuntimeConfig(
            max_steps=max_steps_override or settings.max_steps,
            max_runtime_seconds=settings.max_runtime_seconds,
            max_failures=settings.max_failures,
            dry_run=dry_run,
        ),
    )
    try:
        return await runtime.run(instruction)
    finally:
        await adapter.aclose()
