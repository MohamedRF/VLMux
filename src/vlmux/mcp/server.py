"""Model Context Protocol server over stdio using the core runtime.

JSON-RPC 2.0, line-delimited. Tools are namespaced ``computer.*`` for the
low-level surface (screenshot-free snapshot and ref-based actions mirror what
agent-desktop exposes as ``desktop_*``). The server constructs no screen or
input resources until a tool call actually needs them, so ``initialize`` and
``tools/list`` work on headless machines.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from vlmux._version import __version__
from vlmux.core import RuntimeResult
from vlmux.observation import ScreenObserver
from vlmux.perception import CaptureOptions, create_screen_capture_provider
from vlmux.protocol import ClickRefAction, SetValueRefAction

_MAX_WAIT_MS = 300_000

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
        "name": "desktop_snapshot",
        "description": (
            "Capture the accessibility tree with element refs (Windows, requires "
            "vlmux[uia]). Refs (e.g. '@s1a2b3:e8') belong to the returned snapshot; "
            "pass them to desktop_click / desktop_set_value. Re-snapshot when a ref "
            "action fails with stale_ref."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Only windows whose title contains this text.",
                },
                "window_id": {"type": "string", "description": "Only this window handle."},
                "interactive_only": {"type": "boolean", "default": True},
                "max_elements": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
            },
        },
    },
    {
        "name": "desktop_click",
        "description": (
            "Invoke an accessibility-tree element by ref (headless; no pointer movement)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "button": {"type": "string", "enum": ["left"], "default": "left"},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "desktop_set_value",
        "description": "Set an accessibility-tree element's value by ref (headless).",
        "inputSchema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}, "value": {"type": "string"}},
            "required": ["ref", "value"],
        },
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
        "description": "Wait for a bounded duration in milliseconds (max 300000).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration_ms": {"type": "integer", "minimum": 0, "maximum": _MAX_WAIT_MS}
            },
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
            "properties": {"application": {"type": "string", "minLength": 1}},
            "required": ["application"],
        },
    },
    {
        "name": "computer.run_task",
        "description": "Run a full VLMux task through the configured model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "minLength": 1},
                "model": {"type": "string"},
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 10_000},
            },
            "required": ["task"],
        },
    },
]


class MCPServer:
    """JSON-RPC 2.0 MCP server reading lines from stdin, writing to stdout."""

    def __init__(
        self,
        *,
        run_task: Any | None = None,
        observer: Any | None = None,
        executor: Any | None = None,
        ui_provider: Any | None = None,
        ui_registry: Any | None = None,
    ) -> None:
        self._observer = observer
        self._executor = executor
        self._ui_provider = ui_provider
        self._ui_registry = ui_registry
        self._run_task = run_task

    # -- lazy component construction --------------------------------------

    def _get_observer(self) -> Any:
        if self._observer is None:
            self._observer = ScreenObserver(create_screen_capture_provider(), CaptureOptions())
        return self._observer

    def _get_executor(self) -> Any:
        if self._executor is None:
            from vlmux.executors import create_computer_executor

            self._executor = create_computer_executor(
                ui_registry=self._ui_registry, ui_provider=self._ui_provider
            )
        return self._executor

    def _get_ui_tree(self) -> tuple[Any, Any]:
        if self._ui_provider is None:
            from vlmux.perception.ui_tree import RefRegistry
            from vlmux.perception.windows_uia import WindowsUITreeProvider

            self._ui_registry = self._ui_registry or RefRegistry()
            self._ui_provider = WindowsUITreeProvider(self._ui_registry)
        return self._ui_provider, self._ui_registry

    # -- JSON-RPC dispatch -------------------------------------------------

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
                    "serverInfo": {"name": "vlmux-mcp", "version": __version__},
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
        except (KeyError, TypeError, ValueError) as error:
            return self._error(message_id, -32602, f"invalid params: {error}")
        except Exception as error:
            return self._error(message_id, -32603, str(error))
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "computer.observe":
            observation = await self._get_observer().capture()
            payload = observation.model_dump(mode="json")
            payload["screen"] = dict(payload["screen"], image="<redacted>")
            return self._text(payload)
        if name == "computer.screenshot":
            observation = await self._get_observer().capture()
            return self._text(observation.model_dump(mode="json")["screen"])
        if name == "desktop_snapshot":
            provider, _registry = self._get_ui_tree()
            max_elements = int(arguments.get("max_elements", 500))
            snapshot = await asyncio.to_thread(
                provider.snapshot,
                window_id=arguments.get("window_id"),
                app=arguments.get("app"),
                interactive_only=bool(arguments.get("interactive_only", True)),
                max_elements=max(1, min(max_elements, 2000)),
            )
            return self._text(snapshot.to_dict())
        if name == "desktop_click":
            ref = str(arguments["ref"])
            result = await self._get_executor().execute(
                ClickRefAction(ref=ref, button=str(arguments.get("button", "left")))
            )
            return self._ref_result(result, "click_ref")
        if name == "desktop_set_value":
            ref = str(arguments["ref"])
            result = await self._get_executor().execute(
                SetValueRefAction(ref=ref, value=str(arguments["value"]))
            )
            return self._ref_result(result, "set_value_ref")
        if name == "computer.click":
            await self._get_executor().click(int(arguments["x"]), int(arguments["y"]))
            return self._text({"ok": True})
        if name == "computer.double_click":
            await self._get_executor().double_click(int(arguments["x"]), int(arguments["y"]))
            return self._text({"ok": True})
        if name == "computer.type":
            await self._get_executor().type_text(str(arguments["text"]))
            return self._text({"ok": True})
        if name == "computer.hotkey":
            keys = arguments["keys"]
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise ValueError("keys must be a list of strings")
            await self._get_executor().hotkey([str(k) for k in keys])
            return self._text({"ok": True})
        if name == "computer.scroll":
            await self._get_executor().scroll(
                int(arguments.get("delta_x", 0)), int(arguments["delta_y"])
            )
            return self._text({"ok": True})
        if name == "computer.drag":
            await self._get_executor().drag(
                int(arguments["start_x"]),
                int(arguments["start_y"]),
                int(arguments["end_x"]),
                int(arguments["end_y"]),
            )
            return self._text({"ok": True})
        if name == "computer.wait":
            duration_ms = int(arguments["duration_ms"])
            if not 0 <= duration_ms <= _MAX_WAIT_MS:
                raise ValueError(f"duration_ms must be between 0 and {_MAX_WAIT_MS}")
            await self._get_executor().wait(duration_ms)
            return self._text({"ok": True})
        if name == "computer.windows":
            return self._text({"windows": await self._get_executor().list_windows()})
        if name == "computer.open_app":
            await self._get_executor().open_app(str(arguments["application"]), [])
            return self._text({"ok": True})
        if name == "computer.run_task":
            return await self._run_task_tool(arguments)
        return self._text({"error": f"unknown tool: {name}"}, is_error=True)

    async def _run_task_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runner = self._run_task
        if runner is None:
            return self._text(
                {"error": "run_task is not configured in this server", "code": "not_configured"},
                is_error=True,
            )
        task_text = str(arguments["task"])
        model = arguments.get("model")
        max_steps = arguments.get("max_steps")
        model_override = str(model) if model is not None else None
        steps_override = int(max_steps) if max_steps is not None else None
        result: RuntimeResult = await runner(
            task_text,
            model_override=model_override,
            max_steps_override=steps_override,
        )
        payload = result.model_dump(mode="json")
        # Strip the bulky internal observation blob from tool output.
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("_final_observation", None)
        return self._text(payload)

    @staticmethod
    def _ref_result(result: Any, action_name: str) -> dict[str, Any]:
        if result.success:
            return MCPServer._text({"ok": True, "action": action_name})
        return MCPServer._text(
            {"error": result.error or "action failed", "code": result.error_code},
            is_error=True,
        )

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
    active = server or MCPServer(run_task=_default_run_task())
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"parse error: {error}"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        if not isinstance(message, dict):
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "invalid request: expected object"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        response = await active.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def _default_run_task() -> Any:
    """Bound MCP's run_task to the real runtime with keyword-only overrides."""

    from vlmux.cli.services import run_task as services_run_task
    from vlmux.config import load_settings

    async def runner(
        instruction: str,
        model_override: str | None = None,
        max_steps_override: int | None = None,
    ) -> RuntimeResult:
        settings = load_settings()
        return await services_run_task(
            instruction,
            settings,
            model_override=model_override,
            max_steps_override=max_steps_override,
        )

    return runner


def main() -> None:
    """Entry point for the ``vlmux-mcp`` console script."""
    asyncio.run(serve_stdio())


__all__ = ["TOOLS", "MCPServer", "main", "serve_stdio"]
