"""Windows desktop executor backed by pynput input controllers."""

from __future__ import annotations

import asyncio
import subprocess
from time import sleep
from typing import Any, Protocol

from vlmux.exceptions import ActionExecutionError
from vlmux.executors.base import ComputerExecutor, MouseButton
from vlmux.platforms.windows import enable_dpi_awareness


class InputBackend(Protocol):
    """Synchronous input-driver boundary used by the Windows executor."""

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


class PynputInputBackend:
    """Real keyboard and mouse input implementation using pynput."""

    def __init__(self) -> None:
        from pynput import keyboard, mouse

        self._keyboard_module = keyboard
        self._mouse_module = mouse
        self._keyboard = keyboard.Controller()
        self._mouse = mouse.Controller()

    def click(
        self,
        x: int,
        y: int,
        button: MouseButton,
        count: int,
        interval_ms: int,
    ) -> None:
        self._mouse.position = (x, y)
        resolved_button = getattr(self._mouse_module.Button, button)
        for index in range(count):
            self._mouse.click(resolved_button, 1)
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
        resolved_key = self._resolve_key(key)
        for index in range(presses):
            self._keyboard.press(resolved_key)
            self._keyboard.release(resolved_key)
            if interval_ms and index < presses - 1:
                sleep(interval_ms / 1000)

    def hotkey(self, keys: list[str]) -> None:
        resolved_keys = [self._resolve_key(key) for key in keys]
        pressed: list[Any] = []
        try:
            for key in resolved_keys:
                self._keyboard.press(key)
                pressed.append(key)
        finally:
            for key in reversed(pressed):
                self._keyboard.release(key)

    def scroll(
        self,
        delta_x: int,
        delta_y: int,
        x: int | None,
        y: int | None,
    ) -> None:
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
        resolved_button = getattr(self._mouse_module.Button, button)
        self._mouse.position = (start_x, start_y)
        self._mouse.press(resolved_button)
        try:
            self.move(end_x, end_y, duration_ms)
        finally:
            self._mouse.release(resolved_button)

    def _resolve_key(self, key: str) -> Any:
        normalized = key.strip().lower().replace("-", "_")
        aliases = {
            "control": "ctrl",
            "escape": "esc",
            "return": "enter",
            "windows": "cmd",
            "win": "cmd",
        }
        normalized = aliases.get(normalized, normalized)
        special_key = getattr(self._keyboard_module.Key, normalized, None)
        if special_key is not None:
            return special_key
        if len(key) == 1:
            return key
        raise ValueError(f"unknown keyboard key: {key}")

    def open_app(self, application: str, arguments: list[str]) -> None:
        aliases = {
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "notepad": "notepad.exe",
        }
        executable = aliases.get(application.strip().casefold(), application)
        subprocess.Popen(
            [executable, *arguments],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )


class WindowsExecutor(ComputerExecutor):
    """Execute desktop input on Windows while keeping pynput isolated."""

    def __init__(self, *, backend: InputBackend | None = None) -> None:
        enable_dpi_awareness()
        try:
            self._backend = backend or PynputInputBackend()
        except Exception as error:
            raise ActionExecutionError("unable to initialize Windows input control") from error

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
        self,
        delta_x: int,
        delta_y: int,
        *,
        x: int | None = None,
        y: int | None = None,
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
        await self._call_backend(
            "drag",
            start_x,
            start_y,
            end_x,
            end_y,
            duration_ms,
            button,
        )

    async def open_app(self, application: str, arguments: list[str]) -> None:
        await self._call_backend("open_app", application, arguments)

    async def _call_backend(self, method_name: str, *arguments: object) -> None:
        method = getattr(self._backend, method_name)
        try:
            await asyncio.to_thread(method, *arguments)
        except Exception as error:
            raise ActionExecutionError(f"Windows input operation '{method_name}' failed") from error
