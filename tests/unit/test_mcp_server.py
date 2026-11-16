"""Tests for the MCP JSON-RPC server (no stdio loop required)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from vlmux.core import Observation, RuntimeResult, RuntimeStatus, ScreenObservation
from vlmux.executors.base import ComputerExecutor, MouseButton
from vlmux.mcp.server import MCPServer
from vlmux.observation import Observer


class FakeObserver(Observer):
    async def capture(self) -> Observation:
        return Observation(screen=ScreenObservation(width=10, height=10, image="aQ=="))


class FakeExecutor(ComputerExecutor):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def click(self, x: int, y: int, *, button: MouseButton = "left") -> None:
        self.calls.append(("click", x, y, button))

    async def double_click(self, x: int, y: int, *, interval_ms: int = 100) -> None:
        self.calls.append(("double_click", x, y))

    async def right_click(self, x: int, y: int) -> None:
        self.calls.append(("right_click", x, y))

    async def move_cursor(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        self.calls.append(("move_cursor", x, y))

    async def type_text(self, text: str, *, interval_ms: int = 0) -> None:
        self.calls.append(("type_text", text))

    async def key(self, key: str, *, presses: int = 1, interval_ms: int = 0) -> None:
        self.calls.append(("key", key))

    async def hotkey(self, keys: list[str]) -> None:
        self.calls.append(("hotkey", tuple(keys)))

    async def scroll(
        self, delta_x: int, delta_y: int, *, x: int | None = None, y: int | None = None
    ) -> None:
        self.calls.append(("scroll", delta_x, delta_y))

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
        self.calls.append(("drag", start_x, start_y, end_x, end_y))

    async def open_app(self, application: str, arguments: list[str]) -> None:
        self.calls.append(("open_app", application))

    async def click_ref(self, ref: str, *, button: MouseButton = "left", clicks: int = 1) -> None:
        self.calls.append(("click_ref", ref, button, clicks))

    async def set_value_ref(self, ref: str, value: str) -> None:
        self.calls.append(("set_value_ref", ref, value))


def _server(**kwargs: Any) -> MCPServer:
    kwargs.setdefault("observer", FakeObserver())
    kwargs.setdefault("executor", FakeExecutor())
    return MCPServer(**kwargs)


def _call_text(response: dict[str, Any]) -> Any:
    return json.loads(response["result"]["content"][0]["text"])


def test_initialize_returns_server_info() -> None:
    server = _server()
    response = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))

    assert response is not None
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["serverInfo"]["name"] == "vlmux-mcp"


def test_tools_list_advertises_ref_tools() -> None:
    server = _server()
    response = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"desktop_snapshot", "desktop_click", "desktop_set_value"} <= names
    assert "computer.run_task" in names


def test_tools_call_computer_click() -> None:
    executor = FakeExecutor()
    server = _server(executor=executor)
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "computer.click", "arguments": {"x": 10, "y": 20}},
            }
        )
    )

    assert _call_text(response) == {"ok": True}
    assert executor.calls == [("click", 10, 20, "left")]


def test_tools_call_missing_argument_is_invalid_params() -> None:
    server = _server()
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "computer.click", "arguments": {"x": 10}},
            }
        )
    )

    assert response is not None
    assert response["error"]["code"] == -32602


def test_tools_call_wait_capped() -> None:
    server = _server()
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "computer.wait", "arguments": {"duration_ms": 300_001}},
            }
        )
    )

    assert response is not None
    assert response["error"]["code"] == -32602


def test_run_task_uses_keyword_overrides() -> None:
    captured: dict[str, Any] = {}

    async def fake_run_task(
        instruction: str,
        *,
        model_override: str | None = None,
        max_steps_override: int | None = None,
    ) -> RuntimeResult:
        captured.update(
            instruction=instruction,
            model_override=model_override,
            max_steps_override=max_steps_override,
        )
        return RuntimeResult(
            task_id="task_1",
            status=RuntimeStatus.SUCCEEDED,
            steps=1,
            duration_ms=1.0,
            message="done",
            metadata={"_final_observation": {"secret": "blob"}},
        )

    server = _server(run_task=fake_run_task)
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "computer.run_task",
                    "arguments": {
                        "task": "open calculator",
                        "model": "ollama/qwen3-vl",
                        "max_steps": 5,
                    },
                },
            }
        )
    )

    assert captured == {
        "instruction": "open calculator",
        "model_override": "ollama/qwen3-vl",
        "max_steps_override": 5,
    }
    payload = _call_text(response)
    assert payload["status"] == "succeeded"
    # The bulky internal observation blob must not leak to tool output.
    assert "_final_observation" not in payload["metadata"]


def test_run_task_not_configured_reports_error() -> None:
    server = _server()
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "computer.run_task", "arguments": {"task": "do a thing"}},
            }
        )
    )

    payload = _call_text(response)
    assert payload["code"] == "not_configured"
    assert response["result"]["isError"] is True


def test_desktop_click_routes_through_executor() -> None:
    executor = FakeExecutor()
    server = _server(executor=executor)
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "desktop_click", "arguments": {"ref": "@a1b2c3:e8"}},
            }
        )
    )

    assert _call_text(response) == {"ok": True, "action": "click_ref"}
    assert executor.calls == [("click_ref", "@a1b2c3:e8", "left", 1)]


def test_unknown_tool_is_error_result() -> None:
    server = _server()
    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "computer.teleport", "arguments": {}},
            }
        )
    )

    assert response is not None
    assert response["result"]["isError"] is True


def test_unknown_method_is_method_not_found() -> None:
    server = _server()
    response = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 3, "method": "bogus/method"}))

    assert response is not None
    assert response["error"]["code"] == -32601
