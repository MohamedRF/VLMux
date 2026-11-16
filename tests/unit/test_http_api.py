"""HTTP API tests: auth, wiring, and bounded behavior (no real screen or model)."""

from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from vlmux.core import RuntimeResult, RuntimeStatus
from vlmux.server.http_api import TaskStore, make_handler


async def _fake_runner(
    instruction: str,
    *,
    model_override: str | None = None,
    max_steps_override: int | None = None,
) -> RuntimeResult:
    return RuntimeResult(
        task_id="task_fake",
        status=RuntimeStatus.SUCCEEDED,
        steps=1,
        duration_ms=1.0,
        message=f"ran {instruction!r}",
        metadata={"usage": {"input_tokens": 1, "output_tokens": 1}},
    )


@pytest.fixture()
def server():
    store = TaskStore()

    def _make(token: str | None = None):
        handler = make_handler(store, _fake_runner, token=token)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, httpd.server_address[1]

    yield _make


def _request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    try:
        return response.status, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return response.status, raw


def test_health_endpoint(server) -> None:
    httpd, port = server()
    try:
        status, body = _request(port, "GET", "/health")
        assert status == 200
        assert body["status"] == "ok"
    finally:
        httpd.shutdown()


def test_task_lifecycle_without_token(server) -> None:
    httpd, port = server()
    try:
        status, body = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "open calculator"}).encode(),
            {"Content-Type": "application/json"},
        )
        assert status == 202
        task_id = body["id"]
        deadline = time.time() + 5
        record: dict[str, Any] = {}
        while time.time() < deadline:
            status, record = _request(port, "GET", f"/v1/tasks/{task_id}")
            if record.get("status") not in ("running", "created"):
                break
            time.sleep(0.05)
        assert record["status"] == "succeeded"
        assert record["result"]["message"] == "ran 'open calculator'"
    finally:
        httpd.shutdown()


def test_missing_task_is_404(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(port, "GET", "/v1/tasks/task_nope")
        assert status == 404
    finally:
        httpd.shutdown()


def test_invalid_json_body_is_400(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(
            port, "POST", "/v1/tasks", b"{nope", {"Content-Type": "application/json"}
        )
        assert status == 400
    finally:
        httpd.shutdown()


def test_missing_task_is_400(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(port, "POST", "/v1/tasks", json.dumps({"model": "x"}).encode())
        assert status == 400
    finally:
        httpd.shutdown()


def test_max_steps_out_of_range_is_400(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "t", "max_steps": 0}).encode(),
        )
        assert status == 400
    finally:
        httpd.shutdown()


def test_bool_max_steps_is_400(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "t", "max_steps": True}).encode(),
        )
        assert status == 400
    finally:
        httpd.shutdown()


def test_oversized_body_is_413(server) -> None:
    httpd, port = server()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/v1/tasks",
            body=b"{}",
            headers={"Content-Length": str(1024 * 1024 + 1)},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 413
        connection.close()
    finally:
        httpd.shutdown()


def test_non_loopback_host_header_without_token_is_401(server) -> None:
    httpd, port = server()
    try:
        status, _body = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "t"}).encode(),
            {"Host": "evil.example.com"},
        )
        assert status == 401
    finally:
        httpd.shutdown()


def test_token_required_when_configured(server) -> None:
    httpd, port = server(token="s3cret")
    try:
        status, _ = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "t"}).encode(),
            {"Host": "evil.example.com"},
        )
        assert status == 401
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/v1/tasks",
            body=json.dumps({"task": "t"}).encode(),
            headers={"Authorization": "Bearer s3cret", "Host": "evil.example.com"},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 202
        connection.close()
    finally:
        httpd.shutdown()


def test_wrong_token_is_401(server) -> None:
    httpd, port = server(token="s3cret")
    try:
        status, _body = _request(
            port,
            "POST",
            "/v1/tasks",
            json.dumps({"task": "t"}).encode(),
            {"Authorization": "Bearer wrong"},
        )
        assert status == 401
    finally:
        httpd.shutdown()


def test_task_store_evicts_oldest() -> None:
    store = TaskStore(capacity=2)
    first = store.create({"task": "a"})
    second = store.create({"task": "b"})
    third = store.create({"task": "c"})

    assert store.get(first) is None
    assert store.get(second) is not None
    assert store.get(third) is not None


def test_concurrent_tasks_complete(server) -> None:
    httpd, port = server()
    try:
        ids = []
        for index in range(4):
            status, body = _request(
                port,
                "POST",
                "/v1/tasks",
                json.dumps({"task": f"task-{index}"}).encode(),
            )
            assert status == 202
            ids.append(body["id"])
        deadline = time.time() + 10
        for task_id in ids:
            while time.time() < deadline:
                _status, record = _request(port, "GET", f"/v1/tasks/{task_id}")
                if record.get("status") == "succeeded":
                    break
                time.sleep(0.05)
            assert record.get("status") == "succeeded"
    finally:
        httpd.shutdown()
