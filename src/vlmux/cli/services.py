"""Composition root shared by Phase 5 CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from vlmux.config import Settings
from vlmux.core import RuntimeResult, Task
from vlmux.events import EventBus
from vlmux.executors import create_computer_executor
from vlmux.models import (
    CredentialStore,
    create_builtin_registry,
    load_provider_catalog,
    resolve_model_reference,
)
from vlmux.observation import HybridObserver, Observer, ScreenObserver, SetOfMarksObserver
from vlmux.perception import (
    CaptureOptions,
    RectangleDetector,
    create_screen_capture_provider,
)
from vlmux.policy import PolicyEngine, RiskLevel
from vlmux.runtime import ConfirmationHandler, Runtime, RuntimeConfig
from vlmux.trace import TraceRecorder


def capture_options_from_settings(settings: Settings) -> CaptureOptions:
    """Translate central settings into perception options."""
    return CaptureOptions(
        max_width=settings.screenshot_max_width,
        max_height=settings.screenshot_max_height,
        image_format=settings.screenshot_format,
        quality=settings.screenshot_quality,
    )


def build_observer(settings: Settings) -> Observer:
    """Build the configured observer chain for a task run."""
    base: Observer = ScreenObserver(
        create_screen_capture_provider(),
        capture_options_from_settings(settings),
    )
    if settings.perception_mode == "set_of_marks":
        return SetOfMarksObserver(base, RectangleDetector())
    if settings.perception_mode == "hybrid":
        return HybridObserver(base, RectangleDetector())
    return base


def build_browser_executor(settings: Settings):  # type: ignore[no-untyped-def]
    """Build a browser executor when a CDP endpoint is configured."""
    if not settings.browser_cdp_url:
        return None
    from vlmux.browser import BrowserExecutor, BrowserSession, WebSocketCDPTransport

    return BrowserExecutor(BrowserSession(WebSocketCDPTransport(settings.browser_cdp_url)))


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
    observer = build_observer(settings)
    executor = None if dry_run else create_computer_executor()
    browser_executor = build_browser_executor(settings)
    recorder: TraceRecorder | None = None
    if settings.record_runs:
        run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        recorder = TraceRecorder(Path(settings.runs_dir) / run_id)
        await recorder.record_task(Task(instruction=instruction))
        if events is not None:
            recorder.attach(events)
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
            loop_threshold=settings.loop_threshold,
        ),
        browser_executor=browser_executor,
        recorder=recorder,
    )
    try:
        return await runtime.run(instruction)
    finally:
        await adapter.aclose()
