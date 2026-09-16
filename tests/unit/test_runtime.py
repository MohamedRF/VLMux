"""Behavior tests for the bounded runtime loop using safe fakes."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from vlmux.core import (
    AgentContext,
    ModelDecision,
    Observation,
    RuntimeStatus,
    ScreenObservation,
    Task,
)
from vlmux.events import EventBus
from vlmux.exceptions import ActionExecutionError, ModelResponseError
from vlmux.executors.base import ComputerExecutor, MouseButton
from vlmux.models.base import ModelAdapter, ModelHealth
from vlmux.observation import Observer
from vlmux.policy import PolicyDecision, PolicyEngine, RiskLevel
from vlmux.protocol import Action, ClickAction, FailAction, FinishAction, WaitAction
from vlmux.runtime import ConfirmationHandler, Runtime, RuntimeConfig


class FakeObserver(Observer):
    def __init__(self) -> None:
        self.captures = 0

    async def capture(self) -> Observation:
        self.captures += 1
        return Observation(screen=ScreenObservation(width=10, height=10, image="aQ=="))


class SlowObserver(Observer):
    async def capture(self) -> Observation:
        await asyncio.sleep(0.05)
        return Observation(screen=ScreenObservation(width=1, height=1, image="aQ=="))


class ScriptedModel(ModelAdapter):
    def __init__(self, script: Sequence[Action | Exception]) -> None:
        self._script = iter(script)
        self.calls = 0

    async def decide(
        self,
        task: Task,
        observation: Observation,
        context: AgentContext,
    ) -> ModelDecision:
        self.calls += 1
        value = next(self._script)
        if isinstance(value, Exception):
            raise value
        return ModelDecision(action=value)

    async def healthcheck(self) -> ModelHealth:
        return ModelHealth(connected=True, provider="fake", model="fake", detail="ok")


class FakeExecutor(ComputerExecutor):
    def __init__(self, *, fail_click: bool = False) -> None:
        self.actions: list[str] = []
        self.fail_click = fail_click

    async def click(self, x: int, y: int, *, button: MouseButton = "left") -> None:
        self.actions.append("click")
        if self.fail_click:
            raise ActionExecutionError("click failed")

    async def double_click(self, x: int, y: int, *, interval_ms: int = 100) -> None:
        self.actions.append("double_click")

    async def right_click(self, x: int, y: int) -> None:
        self.actions.append("right_click")

    async def move_cursor(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        self.actions.append("move_cursor")

    async def type_text(self, text: str, *, interval_ms: int = 0) -> None:
        self.actions.append("type")

    async def key(self, key: str, *, presses: int = 1, interval_ms: int = 0) -> None:
        self.actions.append("key")

    async def hotkey(self, keys: list[str]) -> None:
        self.actions.append("hotkey")

    async def scroll(
        self,
        delta_x: int,
        delta_y: int,
        *,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        self.actions.append("scroll")

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration_ms: int = 500,
        button: MouseButton = "left",
    ) -> None:
        self.actions.append("drag")

    async def open_app(self, application: str, arguments: list[str]) -> None:
        self.actions.append("open_app")


def build_runtime(
    script: Sequence[Action | Exception],
    *,
    executor: FakeExecutor | None = None,
    config: RuntimeConfig | None = None,
    policy: PolicyEngine | None = None,
    events: EventBus | None = None,
    confirmation_handler: ConfirmationHandler | None = None,
) -> tuple[Runtime, FakeObserver, FakeExecutor]:
    observer = FakeObserver()
    fake_executor = executor or FakeExecutor()
    runtime = Runtime(
        model=ScriptedModel(script),
        observer=observer,
        executor=fake_executor,
        config=config,
        policy=policy,
        events=events,
        confirmation_handler=confirmation_handler,
    )
    return runtime, observer, fake_executor


def test_successful_action_then_finish() -> None:
    runtime, observer, executor = build_runtime(
        [ClickAction(x=1, y=1), FinishAction(message="done")]
    )

    result = asyncio.run(runtime.run("complete task"))

    assert result.status is RuntimeStatus.SUCCEEDED
    assert result.steps == 2
    assert result.message == "done"
    assert observer.captures == 2
    assert executor.actions == ["click"]


def test_fail_action_terminates_without_executor() -> None:
    runtime, _, executor = build_runtime([FailAction(reason="blocked")])

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.FAILED
    assert result.message == "blocked"
    assert executor.actions == []


def test_dry_run_returns_first_action_without_execution_or_confirmation() -> None:
    runtime, _, executor = build_runtime(
        [ClickAction(x=1, y=1)],
        config=RuntimeConfig(dry_run=True),
        policy=PolicyEngine(confirm={RiskLevel.SAFE}),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.DRY_RUN
    assert isinstance(result.final_action, ClickAction)
    assert executor.actions == []


def test_max_steps_stops_repeated_actions() -> None:
    runtime, observer, _ = build_runtime(
        [WaitAction(duration_ms=0), WaitAction(duration_ms=0)],
        config=RuntimeConfig(max_steps=2),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.MAX_STEPS_EXCEEDED
    assert result.steps == 2
    assert observer.captures == 2


def test_repeated_executor_failures_stop_at_limit() -> None:
    executor = FakeExecutor(fail_click=True)
    runtime, _, _ = build_runtime(
        [ClickAction(x=1, y=1), ClickAction(x=1, y=1)],
        executor=executor,
        config=RuntimeConfig(max_failures=2),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.FAILED
    assert result.steps == 2
    assert result.message == "click failed"


def test_repeated_model_failures_stop_at_limit() -> None:
    runtime, _, _ = build_runtime(
        [ModelResponseError("bad one"), ModelResponseError("bad two")],
        config=RuntimeConfig(max_failures=2),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.FAILED
    assert result.message == "bad two"


def test_policy_denial_prevents_execution() -> None:
    runtime, _, executor = build_runtime(
        [ClickAction(x=1, y=1)],
        policy=PolicyEngine(confirm=set(), deny={RiskLevel.SAFE}),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.FAILED
    assert "denies" in (result.message or "")
    assert executor.actions == []


def test_confirmation_handler_can_approve_action() -> None:
    approvals: list[str] = []

    async def approve(action: Action, decision: PolicyDecision) -> bool:
        approvals.append(action.type)
        return True

    runtime, _, executor = build_runtime(
        [ClickAction(x=1, y=1), FinishAction()],
        policy=PolicyEngine(confirm={RiskLevel.SAFE}),
        confirmation_handler=approve,
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.SUCCEEDED
    assert approvals == ["click", "finish"]
    assert executor.actions == ["click"]


def test_timeout_returns_structured_result() -> None:
    runtime = Runtime(
        model=ScriptedModel([FinishAction()]),
        observer=SlowObserver(),
        executor=FakeExecutor(),
        config=RuntimeConfig(max_runtime_seconds=0.001),
    )

    result = asyncio.run(runtime.run("task"))

    assert result.status is RuntimeStatus.TIMED_OUT


def test_runtime_emits_trace_events() -> None:
    events = EventBus()
    names: list[str] = []
    events.subscribe(lambda event: names.append(event.name))
    runtime, _, _ = build_runtime([FinishAction()], events=events)

    asyncio.run(runtime.run("task"))

    assert names == [
        "task.started",
        "observation.created",
        "model.requested",
        "model.responded",
        "action.proposed",
        "action.approved",
        "task.completed",
    ]
