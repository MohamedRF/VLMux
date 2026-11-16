"""Local REST API exposing the same runtime over HTTP.

Built on the standard library so VLMux keeps its minimal dependency set.
Task execution runs on a worker thread; results are kept in a bounded
in-memory store.

Security model
--------------
By default the API binds to ``127.0.0.1`` without a token, which is still
reachable by any local process *and by browser tabs* (a cross-origin page can
POST with ``Content-Type: text/plain`` and no CORS preflight). To close that
hole the server additionally rejects requests whose ``Host`` header is not a
loopback name whenever no token is configured, and supports a bearer token
for defense in depth::

    VLMUX_API_TOKEN=secret vlmux serve
    vlmux serve --token secret

A token is always required when binding to a non-loopback address. Treat the
token as a credential: anyone holding it can drive the computer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from vlmux._version import __version__
from vlmux.config import load_settings
from vlmux.core import RuntimeResult
from vlmux.observation import ScreenObserver
from vlmux.perception import CaptureOptions, create_screen_capture_provider

logger = logging.getLogger("vlmux.server")

_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB
_MAX_STORED_TASKS = 256
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _is_loopback_host(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.strip().rsplit(":", 1)[0].lower()
    return host in _LOOPBACK_HOSTS


class TaskStore:
    """Thread-safe, bounded in-memory store of task results."""

    def __init__(self, capacity: int = _MAX_STORED_TASKS) -> None:
        self._lock = threading.Lock()
        self._capacity = capacity
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(self, record: dict[str, Any]) -> str:
        task_id = f"task_{uuid.uuid4().hex}"
        with self._lock:
            while len(self._tasks) >= self._capacity:
                oldest = next(iter(self._tasks))
                del self._tasks[oldest]
            self._tasks[task_id] = {"id": task_id, "status": "running", **record}
        return task_id

    def update(self, task_id: str, **fields: Any) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(fields)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return dict(record) if record else None


def make_handler(
    store: TaskStore, run_task: Any, *, token: str | None = None
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to the store, task runner, and auth token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"vlmux/{__version__}"

        def log_message(self, format: str, *args: Any) -> None:
            return

        # -- auth and response helpers ------------------------------------

        def _authorized(self) -> bool:
            if token is None:
                # No token configured: only loopback Host headers are accepted,
                # which blocks browser-based cross-origin requests and DNS
                # rebinding against the loopback bind.
                return _is_loopback_host(self.headers.get("Host"))
            provided = self.headers.get("Authorization", "")
            return provided == f"Bearer {token}"

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _drain_best_effort(self, limit: int = 262_144) -> None:
            """Discard a bounded amount of pending body so the client can read our reply."""
            try:
                self.connection.settimeout(0.25)
                remaining = limit
                while remaining > 0:
                    chunk = self.rfile.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except Exception:
                pass

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._send_json(401, {"error": "unauthorized"})
            return False

        # -- routes --------------------------------------------------------

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "version": __version__})
                return
            if not self._require_auth():
                return
            if self.path == "/v1/observe":
                self._observe()
            elif self.path.startswith("/v1/tasks/"):
                task_id = self.path.removeprefix("/v1/tasks/")
                record = store.get(task_id)
                if record is None:
                    self._send_json(404, {"error": "task not found"})
                else:
                    self._send_json(200, record)
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/v1/tasks":
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "invalid content length"})
                return
            if length > _MAX_BODY_BYTES:
                self._send_json(413, {"error": "request body too large"})
                self._drain_best_effort()
                return
            # Drain the request body before replying regardless of outcome;
            # otherwise some platforms RST the connection and swallow the response.
            raw_body = self.rfile.read(length) if length > 0 else b""
            if not self._require_auth():
                return
            try:
                body = json.loads(raw_body or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid JSON body"})
                return
            if not isinstance(body, dict):
                self._send_json(400, {"error": "request body must be a JSON object"})
                return
            task_text = body.get("task")
            if not isinstance(task_text, str) or not task_text.strip():
                self._send_json(400, {"error": "task is required"})
                return
            task_text = task_text.strip()
            if len(task_text) > 10_000:
                self._send_json(400, {"error": "task is too long"})
                return
            model = body.get("model")
            if model is not None and (not isinstance(model, str) or len(model) > 512):
                self._send_json(400, {"error": "model must be a short string"})
                return
            max_steps = body.get("max_steps")
            if max_steps is not None and (
                not isinstance(max_steps, int)
                or isinstance(max_steps, bool)
                or not 1 <= max_steps <= 10_000
            ):
                self._send_json(400, {"error": "max_steps must be an integer between 1 and 10000"})
                return
            task_id = store.create({"task": task_text, "model": model, "max_steps": max_steps})
            threading.Thread(
                target=self._execute,
                args=(task_id, task_text, model, max_steps),
                daemon=True,
            ).start()
            self._send_json(202, {"id": task_id, "status": "running"})

        # -- workers --------------------------------------------------------

        def _execute(self, task_id: str, task_text: str, model: Any, max_steps: Any) -> None:
            try:
                result: RuntimeResult = asyncio.run(
                    run_task(task_text, model_override=model, max_steps_override=max_steps)
                )
                store.update(
                    task_id,
                    status=result.status.value,
                    result=result.model_dump(mode="json"),
                )
            except Exception:
                logger.exception("task %s failed", task_id)
                store.update(task_id, status="failed", error="task failed to complete")

        def _observe(self) -> None:
            try:
                observer = ScreenObserver(create_screen_capture_provider(), CaptureOptions())
                observation = asyncio.run(observer.capture())
                payload = observation.model_dump(mode="json")
                payload["screen"] = dict(payload["screen"], image="<redacted>")
                self._send_json(200, payload)
            except Exception:
                logger.exception("observe failed")
                self._send_json(500, {"error": "observe failed"})

    return Handler


def _build_runtime_runner() -> Any:
    """Return a runner matching the public run_task signature."""

    from vlmux.cli.services import run_task as default_run_task

    async def runner(
        instruction: str,
        model_override: str | None = None,
        max_steps_override: int | None = None,
    ) -> RuntimeResult:
        settings = load_settings()
        return await default_run_task(
            instruction,
            settings,
            model_override=model_override,
            max_steps_override=max_steps_override,
        )

    return runner


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    run_task: Any | None = None,
    *,
    token: str | None = None,
) -> None:
    """Start the HTTP API server (blocks until interrupted).

    ``token`` falls back to the ``VLMUX_API_TOKEN`` environment variable.
    A non-loopback ``host`` always requires a token.
    """
    token = token or os.environ.get("VLMUX_API_TOKEN") or None
    if _is_loopback_host(host):
        if token is None:
            print(
                "warning: running without a token; set VLMUX_API_TOKEN or pass --token to "
                "require authentication (recommended)"
            )
    else:
        if token is None:
            raise ValueError(
                "refusing to bind a non-loopback address without an API token; "
                "set VLMUX_API_TOKEN or pass --token"
            )
    if run_task is None:
        run_task = _build_runtime_runner()
    store = TaskStore()
    handler = make_handler(store, run_task, token=token)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"VLMux API listening on http://{host}:{port} (vlmux {__version__})")
    print("Endpoints: GET /health, GET /v1/observe, POST /v1/tasks, GET /v1/tasks/:id")
    if token is not None:
        print("Authentication: Authorization: Bearer <token> required")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
