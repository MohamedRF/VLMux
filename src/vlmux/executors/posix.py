"""Shared pynput-backed desktop executor base for macOS and Linux."""

from __future__ import annotations

import asyncio
from time import sleep
from typing import Any, Protocol

from vlmux.exceptions import ActionExecutionError
from vlmux.executors.base import ComputerExecutor, MouseButton


class PosixInputBackend(Protocol):
    """Synchronous input-driver boundary for POSIX desktop executors."""

    def click(self, x: int, y: int, button: MouseButton, count: int, interval_ms: int) -> None: ...

    def move(self, x: int, y: int, duration_ms: int) -> None: ...

    def type_text(self, text: str, interval_ms: int) -> None: ...

    def press_key(self, key: str, presses: int, interval_ms: int) -> None: ...

    def hotkey(self, keys: list[str]) -> None: ...

    def scroll(self, delta_x: int, delta_y: int, x: int | None, y: int | None) -> None: ...

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
        button: MouseButton,
    ) -> None: ...

    def open_app(self, application: str, arguments: list[str]) -> None: ...


class PynputPosixBackend:
    """Real mouse and keyboard input via pynput for macOS and Linux."""

    def __init__(self) -> None:
        from pynput import keyboard, mouse

        self._keyboard_module = keyboard
        self._mouse_module = mouse
        self._keyboard = keyboard.Controller()
        self._mouse = mouse.Controller()

    def click(self, x: int, y: int, button: MouseButton, count: int, interval_ms: int) -> None:
        self._mouse.position = (x, y)
        resolved = getattr(self._mouse_module.Button, button)
        for index in range(count):
            self._mouse.click(resolved, 1)
            if interval_ms and index < count - 1:
                sleep(interval_ms / 1000)

    def move(self, x: int, y: int, duration_ms: int) -> None:
        if duration_ms == 0:
            self._mouse.position = (x, y)
            return
        start_x, start_y = self._mouse.position
        steps = max(1, min(duration_ms // 10, 100))
        delay = duration_ms / steps / 1000
        for step in range(1, steps + 1):
            fraction = step / steps
            self._mouse.position = (
                round(start_x + (x - start_x) * fraction),
                round(start_y + (y - start_y) * fraction),
            )
            sleep(delay)

    def type_text(self, text: str, interval_ms: int) -> None:
        if interval_ms == 0:
            self._keyboard.type(text)
            return
        for character in text:
            self._keyboard.type(character)
            sleep(interval_ms / 1000)

    def press_key(self, key: str, presses: int, interval_ms: int) -> None:
        resolved = self._resolve_key(key)
        for index in range(presses):
            self._keyboard.press(resolved)
            self._keyboard.release(resolved)
            if interval_ms and index < presses - 1:
                sleep(interval_ms / 1000)

    def hotkey(self, keys: list[str]) -> None:
        resolved = [self._resolve_key(key) for key in keys]
        pressed: list[Any] = []
        try:
            for key in resolved:
                self._keyboard.press(key)
                pressed.append(key)
        finally:
            for key in reversed(pressed):
                self._keyboard.release(key)

    def scroll(self, delta_x: int, delta_y: int, x: int | None, y: int | None) -> None:
        if x is not None and y is not None:
            self._mouse.position = (x, y)
        self._mouse.scroll(delta_x, delta_y)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
        button: MouseButton,
    ) -> None:
        resolved = getattr(self._mouse_module.Button, button)
        self._mouse.position = (start_x, start_y)
        self._mouse.press(resolved)
        try:
            self.move(end_x, end_y, duration_ms)
        finally:
            self._mouse.release(resolved)

    def _resolve_key(self, key: str) -> Any:
        normalized = key.strip().lower().replace("-", "_")
        aliases = {
            "control": "ctrl",
            "escape": "esc",
            "return": "enter",
            "cmd": "command",
            "command": "command",
        }
        normalized = aliases.get(normalized, normalized)
        special = getattr(self._keyboard_module.Key, normalized, None)
        if special is not None:
            return special
        if len(key) == 1:
            return key
        raise ValueError(f"unknown keyboard key: {key}")

    def open_app(self, application: str, arguments: list[str]) -> None:
        raise ActionExecutionError("open_app is implemented by the platform executor")


class PosixExecutor(ComputerExecutor):
    """pynput-backed executor; subclasses customize application launching."""

    platform_name = "POSIX"

    def __init__(self, *, backend: PosixInputBackend | None = None) -> None:
        try:
            self._backend = backend or PynputPosixBackend()
        except Exception as error:
            raise ActionExecutionError(
                f"unable to initialize {self.platform_name} input control"
            ) from error

    async def click(self, x: int, y: int, *, button: MouseButton = "left") -> None:
        await self._call_backend("click", x, y, button, 1, 0)

    async def double_click(self, x: int, y: int, *, interval_ms: int = 100) -> None:
        await self._call_backend("click", x, y, "left", 2, interval_ms)

    async def right_click(self, x: int, y: int) -> None:
        await self._call_backend("click", x, y, "right", 1, 0)

    async def move_cursor(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        await self._call_backend("move", x, y, duration_ms)

    async def type_text(self, text: str, *, interval_ms: int = 0) -> None:
        await self._call_backend("type_text", text, interval_ms)

    async def key(self, key: str, *, presses: int = 1, interval_ms: int = 0) -> None:
        await self._call_backend("press_key", key, presses, interval_ms)

    async def hotkey(self, keys: list[str]) -> None:
        await self._call_backend("hotkey", keys)

    async def scroll(
        self, delta_x: int, delta_y: int, *, x: int | None = None, y: int | None = None
    ) -> None:
        await self._call_backend("scroll", delta_x, delta_y, x, y)

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
        await self._call_backend("drag", start_x, start_y, end_x, end_y, duration_ms, button)

    async def open_app(self, application: str, arguments: list[str]) -> None:
        await self._call_backend("open_app", application, arguments)

    async def _call_backend(self, method_name: str, *arguments: object) -> None:
        method = getattr(self._backend, method_name)
        try:
            await asyncio.to_thread(method, *arguments)
        except ActionExecutionError:
            raise
        except Exception as error:
            raise ActionExecutionError(
                f"{self.platform_name} input operation '{method_name}' failed"
            ) from error
