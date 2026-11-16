"""Abstract computer executor and VAP dispatch."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Literal

from vlmux.core import ActionResult
from vlmux.exceptions import (
    ActionExecutionError,
    ActionValidationError,
    RefUnavailableError,
    error_code,
)
from vlmux.protocol import (
    Action,
    ClickAction,
    ClickRefAction,
    CloseWindowAction,
    DoubleClickAction,
    DragAction,
    FocusWindowAction,
    HotkeyAction,
    KeyAction,
    MoveCursorAction,
    OpenAppAction,
    RightClickAction,
    ScrollAction,
    SetValueRefAction,
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
                error_code=error_code(error),
            )
        except ActionValidationError as error:
            # Stale or ambiguous element references land here; the model can
            # recover by taking a fresh snapshot.
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=(perf_counter() - started) * 1000,
                error=str(error),
                error_code=error_code(error),
            )
        except Exception as error:
            # Defense-in-depth: a buggy backend must produce a failed result,
            # never an unhandled exception out of the task loop.
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=(perf_counter() - started) * 1000,
                error=f"unexpected executor failure ({type(error).__name__}): {error}",
                error_code="internal_error",
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
        elif isinstance(action, FocusWindowAction):
            await self.focus_window(action.window_id, action.title)
        elif isinstance(action, CloseWindowAction):
            await self.close_window(action.window_id, action.title)
        elif isinstance(action, ClickRefAction):
            await self.click_ref(action.ref, button=action.button, clicks=action.clicks)
        elif isinstance(action, SetValueRefAction):
            await self.set_value_ref(action.ref, action.value)
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

    async def focus_window(self, window_id: str | None, title: str | None) -> None:
        """Bring a matching window to the foreground."""
        raise ActionExecutionError("focus_window is not supported by this executor")

    async def close_window(self, window_id: str | None, title: str | None) -> None:
        """Close a matching window."""
        raise ActionExecutionError("close_window is not supported by this executor")

    async def click_ref(self, ref: str, *, button: MouseButton = "left", clicks: int = 1) -> None:
        """Invoke an accessibility-tree element reference (headless).

        Implementations must resolve ``ref`` against the registry used when the
        reference was minted and invoke the control without moving the pointer.
        The default raises :class:`RefUnavailableError`.
        """
        raise RefUnavailableError(
            "ref-based actions require an accessibility backend; "
            "install vlmux[uia] on Windows and run with the ui_tree perception mode"
        )

    async def set_value_ref(self, ref: str, value: str) -> None:
        """Set an accessibility-tree element's value (headless).

        The default raises :class:`RefUnavailableError`.
        """
        raise RefUnavailableError(
            "ref-based actions require an accessibility backend; "
            "install vlmux[uia] on Windows and run with the ui_tree perception mode"
        )

    async def list_windows(self) -> list[dict[str, object]]:
        """List windows known to this executor, if discoverable."""
        return []
