"""Python SDK for VLMux: high-level agent and low-level computer control."""

from __future__ import annotations

from typing import Any

from vlmux.config import load_settings
from vlmux.core import RuntimeResult
from vlmux.executors import ComputerExecutor, create_computer_executor


class Computer:
    """Direct computer control without a model (same executor as the runtime)."""

    def __init__(self, executor: ComputerExecutor | None = None) -> None:
        self._executor = executor or create_computer_executor()

    @property
    def executor(self) -> ComputerExecutor:
        """Return the underlying executor."""
        return self._executor

    async def click(self, x: int, y: int) -> None:
        """Click once at absolute screen coordinates."""
        await self._executor.click(x, y)

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at absolute screen coordinates."""
        await self._executor.double_click(x, y)

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at absolute screen coordinates."""
        await self._executor.right_click(x, y)

    async def type(self, text: str) -> None:
        """Type text into the focused control."""
        await self._executor.type_text(text)

    async def hotkey(self, keys: list[str]) -> None:
        """Press a keyboard shortcut."""
        await self._executor.hotkey(keys)

    async def scroll(self, delta_y: int, *, delta_x: int = 0) -> None:
        """Scroll by signed pixel deltas."""
        await self._executor.scroll(delta_x, delta_y)

    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        """Drag between two absolute coordinates."""
        await self._executor.drag(start_x, start_y, end_x, end_y)

    async def wait(self, duration_ms: int) -> None:
        """Wait for a bounded duration."""
        await self._executor.wait(duration_ms)

    async def open_app(self, application: str) -> None:
        """Launch an application without a shell."""
        await self._executor.open_app(application, [])


class VLMux:
    """High-level computer-use agent.

    Usage:
        agent = VLMux(model="ollama/qwen3-vl")
        result = await agent.run("Open calculator and calculate 42 * 88")
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        provider: str | None = None,
        max_steps: int | None = None,
        dry_run: bool = False,
        events: Any | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._max_steps = max_steps
        self._dry_run = dry_run
        self._events = events

    async def run(self, task: str) -> RuntimeResult:
        """Run one computer-use task to completion."""
        from vlmux.cli.services import run_task

        settings = load_settings(
            cli_overrides={
                "model": self._model,
                "provider": self._provider,
                "max_steps": self._max_steps,
            }
        )
        return await run_task(
            task,
            settings,
            dry_run=self._dry_run,
            events=self._events,
        )
