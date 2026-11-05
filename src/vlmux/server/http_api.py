"""Local REST API exposing the same runtime over HTTP.

Built on the standard library so VLMux keeps its minimal dependency set.
Task execution runs on a single worker thread; results are kept in memory.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from vlmux.config import load_settings
from vlmux.core import RuntimeResult
from vlmux.observation import ScreenObserver
from vlmux.perception import CaptureOptions, create_screen_capture_provider


class TaskStore:
    """Thread-safe in-memory store of task results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(self, record: dict[str, Any]) -> str:
        task_id = f"task_{uuid.uuid4().hex}"
        with self._lock:
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


def make_handler(store: TaskStore, run_task: Any) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to the store and task runner."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "VLMux/0.1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
            elif self.path == "/v1/observe":
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
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid JSON body"})
                return
            task_text = body.get("task")
            if not isinstance(task_text, str) or not task_text.strip():
                self._send_json(400, {"error": "task is required"})
                return
            task_id = store.create(
                {"task": task_text, "model": body.get("model"), "max_steps": body.get("max_steps")}
            )
            threading.Thread(
                target=self._execute,
                args=(task_id, task_text, body.get("model"), body.get("max_steps")),
                daemon=True,
            ).start()
            self._send_json(202, {"id": task_id, "status": "running"})

        def _execute(self, task_id: str, task_text: str, model: Any, max_steps: Any) -> None:
            try:
                result: RuntimeResult = asyncio.run(run_task(task_text, model, max_steps))
                store.update(
                    task_id,
                    status=result.status.value,
                    result=result.model_dump(mode="json"),
                )
            except Exception as error:
                store.update(task_id, status="failed", error=str(error))

        def _observe(self) -> None:
            try:
                observer = ScreenObserver(create_screen_capture_provider(), CaptureOptions())
                observation = asyncio.run(observer.capture())
                payload = observation.model_dump(mode="json")
                payload["screen"] = dict(payload["screen"], image="<redacted>")
                self._send_json(200, payload)
            except Exception as error:
                self._send_json(500, {"error": str(error)})

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, run_task: Any | None = None) -> None:
    """Start the HTTP API server (blocks until interrupted)."""
    from vlmux.cli.services import run_task as default_run_task

    settings = load_settings()
    store = TaskStore()
    handler = make_handler(store, run_task or default_run_task)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"VLMux API listening on http://{host}:{port} (model: {settings.model or 'unset'})")
    print("Endpoints: GET /health, GET /v1/observe, POST /v1/tasks, GET /v1/tasks/:id")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
