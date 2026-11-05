"""Tests for runtime loop detection, mark resolution, and usage tracking."""

from __future__ import annotations

import asyncio

from vlmux.core import (
    AgentContext,
    ModelDecision,
    Observation,
    RuntimeStatus,
    ScreenObservation,
    Task,
)
from vlmux.events import EventBus
from vlmux.executors.base import ComputerExecutor, MouseButton
from vlmux.models.base import ModelAdapter, ModelHealth
from vlmux.observation import Observer
from vlmux.protocol import ClickAction, ClickMarkAction, FinishAction
from vlmux.runtime import Runtime, RuntimeConfig
from vlmux.runtime.engine import action_signature, perceptual_hash, screen_hashes_match


class FakeObserver(Observer):
    def __init__(self, metadata: dict | None = None) -> None:
        self._metadata = metadata or {}

    async def capture(self) -> Observation:
        return Observation(
            screen=ScreenObservation(width=10, height=10, image="aQ=="),
            metadata=dict(self._metadata),
        )


class ScriptedModel(ModelAdapter):
    def __init__(self, actions: list) -> None:
        self._actions = iter(actions)

    async def decide(
        self, task: Task, observation: Observation, context: AgentContext
    ) -> ModelDecision:
        return ModelDecision(action=next(self._actions), input_tokens=10, output_tokens=5)

    async def healthcheck(self) -> ModelHealth:
        return ModelHealth(connected=True, provider="fake", model="fake", detail="ok")


class FakeExecutor(ComputerExecutor):
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int, *, button: MouseButton = "left") -> None:
        self.clicks.append((x, y))

    async def double_click(self, x: int, y: int, *, interval_ms: int = 100) -> None: ...
    async def right_click(self, x: int, y: int) -> None: ...
    async def move_cursor(self, x: int, y: int, *, duration_ms: int = 0) -> None: ...
    async def type_text(self, text: str, *, interval_ms: int = 0) -> None: ...
    async def key(self, key: str, *, presses: int = 1, interval_ms: int = 0) -> None: ...
    async def hotkey(self, keys: list[str]) -> None: ...
    async def scroll(
        self, delta_x: int, delta_y: int, *, x: int | None = None, y: int | None = None
    ) -> None: ...
    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration_ms: int = 500,
        button: MouseButton = "left",
    ) -> None: ...
    async def open_app(self, application: str, arguments: list[str]) -> None: ...


def test_action_signature_distinguishes_coordinates() -> None:
    assert action_signature(ClickAction(x=1, y=2)) != action_signature(ClickAction(x=3, y=2))
    assert action_signature(ClickMarkAction(mark=3)) == "click_mark:3"


def test_loop_detection_terminates() -> None:
    events = EventBus()
    names: list[str] = []
    events.subscribe(lambda event: names.append(event.name))
    runtime = Runtime(
        model=ScriptedModel([ClickAction(x=1, y=1)] * 6),
        observer=FakeObserver(),
        executor=FakeExecutor(),
        config=RuntimeConfig(max_steps=10, loop_threshold=3),
        events=events,
    )
    result = asyncio.run(runtime.run("task"))
    assert result.status is RuntimeStatus.FAILED
    assert "loop detected" in (result.message or "")
    assert "runtime.loop_detected" in names


def test_click_mark_resolves_to_click() -> None:
    executor = FakeExecutor()
    runtime = Runtime(
        model=ScriptedModel([ClickMarkAction(mark=2), FinishAction()]),
        observer=FakeObserver({"set_of_marks": {"2": {"center": [4, 6]}}}),
        executor=executor,
    )
    result = asyncio.run(runtime.run("task"))
    assert result.status is RuntimeStatus.SUCCEEDED
    assert executor.clicks == [(4, 6)]


def test_click_mark_without_marks_fails() -> None:
    runtime = Runtime(
        model=ScriptedModel([ClickMarkAction(mark=1)]),
        observer=FakeObserver(),
        executor=FakeExecutor(),
    )
    result = asyncio.run(runtime.run("task"))
    assert result.status is RuntimeStatus.FAILED
    assert "Set-of-Marks" in (result.message or "")


def test_usage_is_aggregated() -> None:
    runtime = Runtime(
        model=ScriptedModel([FinishAction()]),
        observer=FakeObserver(),
        executor=FakeExecutor(),
    )
    result = asyncio.run(runtime.run("task"))
    assert result.metadata["usage"] == {"input_tokens": 10, "output_tokens": 5}


def test_perceptual_hash_is_stable_for_same_screen() -> None:
    screen = ScreenObservation(width=10, height=10, image="aQ==")
    assert perceptual_hash(screen) == perceptual_hash(screen)
    assert screen_hashes_match("abc", "abc") is True
    assert screen_hashes_match("abc", "def") is False
