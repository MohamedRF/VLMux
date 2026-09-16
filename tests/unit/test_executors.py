"""Tests for VAP dispatch and the Windows executor boundary."""

import asyncio
from typing import Any

import pytest

from vlmux.exceptions import ActionExecutionError, UnsupportedPlatformError
from vlmux.executors import PynputInputBackend, WindowsExecutor
from vlmux.executors.base import MouseButton
from vlmux.executors.factory import create_computer_executor
from vlmux.protocol import (
    Action,
    ClickAction,
    DoubleClickAction,
    DragAction,
    FinishAction,
    HotkeyAction,
    KeyAction,
    MoveCursorAction,
    OpenAppAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
)


class FakeInputBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail_operation: str | None = None

    def _record(self, operation: str, *arguments: object) -> None:
        if self.fail_operation == operation:
            raise RuntimeError("backend details")
        self.calls.append((operation, *arguments))

    def click(self, x: int, y: int, button: MouseButton, count: int, interval_ms: int) -> None:
        self._record("click", x, y, button, count, interval_ms)

    def move(self, x: int, y: int, duration_ms: int) -> None:
        self._record("move", x, y, duration_ms)

    def type_text(self, text: str, interval_ms: int) -> None:
        self._record("type_text", text, interval_ms)

    def press_key(self, key: str, presses: int, interval_ms: int) -> None:
        self._record("press_key", key, presses, interval_ms)

    def hotkey(self, keys: list[str]) -> None:
        self._record("hotkey", keys)

    def scroll(
        self,
        delta_x: int,
        delta_y: int,
        x: int | None,
        y: int | None,
    ) -> None:
        self._record("scroll", delta_x, delta_y, x, y)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
        button: MouseButton,
    ) -> None:
        self._record("drag", start_x, start_y, end_x, end_y, duration_ms, button)

    def open_app(self, application: str, arguments: list[str]) -> None:
        self._record("open_app", application, arguments)


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ClickAction(x=1, y=2), ("click", 1, 2, "left", 1, 0)),
        (DoubleClickAction(x=3, y=4, interval_ms=90), ("click", 3, 4, "left", 2, 90)),
        (RightClickAction(x=5, y=6), ("click", 5, 6, "right", 1, 0)),
        (MoveCursorAction(x=7, y=8, duration_ms=10), ("move", 7, 8, 10)),
        (TypeAction(text="hello", interval_ms=2), ("type_text", "hello", 2)),
        (KeyAction(key="enter", presses=2, interval_ms=3), ("press_key", "enter", 2, 3)),
        (HotkeyAction(keys=["ctrl", "s"]), ("hotkey", ["ctrl", "s"])),
        (ScrollAction(delta_x=1, delta_y=-2, x=3, y=4), ("scroll", 1, -2, 3, 4)),
        (OpenAppAction(application="Calculator"), ("open_app", "Calculator", [])),
        (
            DragAction(start_x=1, start_y=2, end_x=3, end_y=4, duration_ms=5),
            ("drag", 1, 2, 3, 4, 5, "left"),
        ),
    ],
)
def test_executor_dispatches_supported_actions(action: Action, expected: tuple[Any, ...]) -> None:
    backend = FakeInputBackend()
    executor = WindowsExecutor(backend=backend)

    result = asyncio.run(executor.execute(action))

    assert result.success
    assert result.error is None
    assert backend.calls == [expected]


def test_wait_action_is_async_and_successful() -> None:
    result = asyncio.run(
        WindowsExecutor(backend=FakeInputBackend()).execute(WaitAction(duration_ms=0))
    )

    assert result.success


def test_unsupported_desktop_action_returns_failed_result() -> None:
    result = asyncio.run(WindowsExecutor(backend=FakeInputBackend()).execute(FinishAction()))

    assert not result.success
    assert result.error is not None
    assert "not supported" in result.error


def test_backend_failure_returns_failed_result_without_leaking_internal_error() -> None:
    backend = FakeInputBackend()
    backend.fail_operation = "click"
    executor = WindowsExecutor(backend=backend)

    result = asyncio.run(executor.execute(ClickAction(x=1, y=2, id="action-1")))

    assert not result.success
    assert result.action_id == "action-1"
    assert result.error == "Windows input operation 'click' failed"
    assert "backend details" not in result.error


def test_direct_primitive_preserves_execution_error_cause() -> None:
    backend = FakeInputBackend()
    backend.fail_operation = "type_text"

    with pytest.raises(ActionExecutionError) as raised:
        asyncio.run(WindowsExecutor(backend=backend).type_text("hello"))

    assert isinstance(raised.value.__cause__, RuntimeError)


def test_factory_rejects_unsupported_platform() -> None:
    with pytest.raises(UnsupportedPlatformError, match="Plan9"):
        create_computer_executor(system_name="Plan9")


def test_application_launch_uses_argument_vector_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(arguments: list[str], **options: Any) -> object:
        calls.append((arguments, options))
        return object()

    monkeypatch.setattr("vlmux.executors.windows.subprocess.Popen", fake_popen)
    backend = object.__new__(PynputInputBackend)

    backend.open_app("Calculator", ["--example"])

    assert calls[0][0] == ["calc.exe", "--example"]
    assert calls[0][1]["shell"] is False
