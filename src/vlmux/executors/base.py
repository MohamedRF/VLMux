"""Abstract computer executor and VAP dispatch."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Literal

from vlmux.core import ActionResult
from vlmux.exceptions import ActionExecutionError
from vlmux.protocol import (
    Action,
    ClickAction,
    DoubleClickAction,
    DragAction,
    HotkeyAction,
    KeyAction,
    MoveCursorAction,
    OpenAppAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
)

MouseButton = Literal["left", "middle", "right"]


class ComputerExecutor(ABC):
    """Translate validated desktop VAP actions into operating-system input."""

    async def execute(self, action: Action) -> ActionResult:
        """Dispatch one supported action and record a structured outcome."""
        started = perf_counter()
        try:
            await self._dispatch(action)
        except ActionExecutionError as error:
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=(perf_counter() - started) * 1000,
                error=str(error),
            )
        return ActionResult(
            action_id=action.id,
            success=True,
            duration_ms=(perf_counter() - started) * 1000,
        )

    async def _dispatch(self, action: Action) -> None:
        if isinstance(action, ClickAction):
            await self.click(action.x, action.y, button=action.button)
        elif isinstance(action, DoubleClickAction):
            await self.double_click(action.x, action.y, interval_ms=action.interval_ms)
        elif isinstance(action, RightClickAction):
            await self.right_click(action.x, action.y)
        elif isinstance(action, MoveCursorAction):
            await self.move_cursor(action.x, action.y, duration_ms=action.duration_ms)
        elif isinstance(action, TypeAction):
            await self.type_text(action.text, interval_ms=action.interval_ms)
        elif isinstance(action, KeyAction):
            await self.key(action.key, presses=action.presses, interval_ms=action.interval_ms)
        elif isinstance(action, HotkeyAction):
            await self.hotkey(action.keys)
        elif isinstance(action, ScrollAction):
            await self.scroll(
                action.delta_x,
                action.delta_y,
                x=action.x,
                y=action.y,
            )
        elif isinstance(action, DragAction):
            await self.drag(
                action.start_x,
                action.start_y,
                action.end_x,
                action.end_y,
                duration_ms=action.duration_ms,
                button=action.button,
            )
        elif isinstance(action, WaitAction):
            await self.wait(action.duration_ms)
        elif isinstance(action, OpenAppAction):
            await self.open_app(action.application, action.arguments)
        else:
            raise ActionExecutionError(
                f"action type '{action.type}' is not supported by the desktop executor"
            )

    @abstractmethod
    async def click(self, x: int, y: int, *, button: MouseButton = "left") -> None:
        """Click once at an absolute screen coordinate."""

    @abstractmethod
    async def double_click(self, x: int, y: int, *, interval_ms: int = 100) -> None:
        """Double-click at an absolute screen coordinate."""

    @abstractmethod
    async def right_click(self, x: int, y: int) -> None:
        """Right-click at an absolute screen coordinate."""

    @abstractmethod
    async def move_cursor(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        """Move the cursor to an absolute screen coordinate."""

    @abstractmethod
    async def type_text(self, text: str, *, interval_ms: int = 0) -> None:
        """Type text into the focused control."""

    @abstractmethod
    async def key(self, key: str, *, presses: int = 1, interval_ms: int = 0) -> None:
        """Press one named key one or more times."""

    @abstractmethod
    async def hotkey(self, keys: list[str]) -> None:
        """Press and release a keyboard shortcut."""

    @abstractmethod
    async def scroll(
        self,
        delta_x: int,
        delta_y: int,
        *,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        """Scroll, optionally after positioning the cursor."""

    @abstractmethod
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
        """Drag between two absolute screen coordinates."""

    async def wait(self, duration_ms: int) -> None:
        """Wait without blocking the asyncio event loop."""
        await asyncio.sleep(duration_ms / 1000)

    @abstractmethod
    async def open_app(self, application: str, arguments: list[str]) -> None:
        """Launch an application without invoking a command shell."""
