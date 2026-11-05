"""Model Context Protocol server over stdio using the core runtime."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from vlmux.core import RuntimeResult
from vlmux.executors import create_computer_executor
from vlmux.observation import ScreenObserver
from vlmux.perception import CaptureOptions, create_screen_capture_provider

TOOLS: list[dict[str, Any]] = [
    {
        "name": "computer.observe",
        "description": "Capture the current screen observation (metadata only).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "computer.screenshot",
        "description": "Capture the current screen as a base64 image.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "computer.click",
        "description": "Click at absolute screen coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "computer.double_click",
        "description": "Double-click at absolute screen coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "computer.type",
        "description": "Type text into the focused control.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "computer.hotkey",
        "description": "Press a keyboard shortcut.",
        "inputSchema": {
            "type": "object",
            "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"],
        },
    },
    {
        "name": "computer.scroll",
        "description": "Scroll by signed pixel deltas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delta_x": {"type": "integer"},
                "delta_y": {"type": "integer"},
            },
            "required": ["delta_y"],
        },
    },
    {
        "name": "computer.drag",
        "description": "Drag between two absolute coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer"},
                "start_y": {"type": "integer"},
                "end_x": {"type": "integer"},
                "end_y": {"type": "integer"},
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    },
    {
        "name": "computer.wait",
        "description": "Wait for a bounded duration in milliseconds.",
        "inputSchema": {
            "type": "object",
            "properties": {"duration_ms": {"type": "integer"}},
            "required": ["duration_ms"],
        },
    },
    {
        "name": "computer.windows",
        "description": "List windows known to the executor.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "computer.open_app",
        "description": "Launch an application without a shell.",
        "inputSchema": {
            "type": "object",
            "properties": {"application": {"type": "string"}},
            "required": ["application"],
        },
    },
    {
        "name": "computer.run_task",
        "description": "Run a full VLMux task through the configured model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "model": {"type": "string"},
                "max_steps": {"type": "integer"},
            },
            "required": ["task"],
        },
    },
]


class MCPServer:
    """JSON-RPC 2.0 MCP server reading lines from stdin, writing to stdout."""

    def __init__(self, *, run_task: Any | None = None) -> None:
        self._observer = ScreenObserver(create_screen_capture_provider(), CaptureOptions())
        self._executor = create_computer_executor()
        self._run_task = run_task

    async def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC message; notifications return None."""
        method = message.get("method", "")
        message_id = message.get("id")
        params = message.get("params") or {}
        if method == "notifications/initialized":
            return None
        if message_id is None:
            return None
        try:
            result: dict[str, Any]
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "vlmux-mcp", "version": "0.1.0"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = await self._call_tool(
                    params.get("name", ""), params.get("arguments") or {}
                )
            elif method == "ping":
                result = {}
            else:
                return self._error(message_id, -32601, f"unknown method: {method}")
        except Exception as error:
            return self._error(message_id, -32603, str(error))
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "computer.observe":
            observation = await self._observer.capture()
            payload = observation.model_dump(mode="json")
            payload["screen"] = dict(payload["screen"], image="<redacted>")
            return self._text(payload)
        if name == "computer.screenshot":
            observation = await self._observer.capture()
            return self._text(observation.model_dump(mode="json")["screen"])
        if name == "computer.click":
            await self._executor.click(int(arguments["x"]), int(arguments["y"]))
            return self._text({"ok": True})
        if name == "computer.double_click":
            await self._executor.double_click(int(arguments["x"]), int(arguments["y"]))
            return self._text({"ok": True})
        if name == "computer.type":
            await self._executor.type_text(str(arguments["text"]))
            return self._text({"ok": True})
        if name == "computer.hotkey":
            await self._executor.hotkey([str(k) for k in arguments["keys"]])
            return self._text({"ok": True})
        if name == "computer.scroll":
            await self._executor.scroll(int(arguments.get("delta_x", 0)), int(arguments["delta_y"]))
            return self._text({"ok": True})
        if name == "computer.drag":
            await self._executor.drag(
                int(arguments["start_x"]),
                int(arguments["start_y"]),
                int(arguments["end_x"]),
                int(arguments["end_y"]),
            )
            return self._text({"ok": True})
        if name == "computer.wait":
            await self._executor.wait(int(arguments["duration_ms"]))
            return self._text({"ok": True})
        if name == "computer.windows":
            return self._text({"windows": await self._executor.list_windows()})
        if name == "computer.open_app":
            await self._executor.open_app(str(arguments["application"]), [])
            return self._text({"ok": True})
        if name == "computer.run_task":
            if self._run_task is None:
                return self._text(
                    {"error": "run_task is not configured in this server"}, is_error=True
                )
            task_text = str(arguments["task"])
            model = arguments.get("model")
            max_steps = arguments.get("max_steps")
            result: RuntimeResult = await self._run_task(task_text, model, max_steps)
            return self._text(result.model_dump(mode="json"))
        return self._text({"error": f"unknown tool: {name}"}, is_error=True)

    @staticmethod
    def _text(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": is_error,
        }

    @staticmethod
    def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


async def serve_stdio(server: MCPServer | None = None) -> None:
    """Run the MCP loop over stdin/stdout (line-delimited JSON-RPC)."""
    active = server or MCPServer()
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = await active.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    """Entry point for the ``vlmux-mcp`` console script."""
    asyncio.run(serve_stdio())
