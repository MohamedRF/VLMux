"""Tests for the OpenAI-compatible multimodal adapter."""

import asyncio
import json

import httpx
import pytest

from vlmux.core import AgentContext, Observation, ScreenObservation, Task
from vlmux.exceptions import ModelConnectionError, ModelResponseError
from vlmux.models import AdapterConfig, OpenAICompatibleAdapter
from vlmux.protocol import ClickAction, FinishAction


def observation() -> Observation:
    return Observation(screen=ScreenObservation(width=2, height=2, image="aQ=="))


def config(**updates: object) -> AdapterConfig:
    values: dict[str, object] = {
        "provider": "openai-compatible",
        "model": "vision-model",
        "api_key": "secret-key",
        "base_url": "https://models.example/v1",
        "request_retries": 0,
        "repair_attempts": 1,
    }
    values.update(updates)
    return AdapterConfig.model_validate(values)


def test_adapter_sends_image_and_returns_normalized_decision() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"type":"click","x":1,"y":1}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(config(), client=client)
    decision = asyncio.run(
        adapter.decide(Task(instruction="click"), observation(), AgentContext(task_id="task"))
    )
    asyncio.run(client.aclose())

    assert isinstance(decision.action, ClickAction)
    assert decision.action.source_model == "vision-model"
    assert decision.action.id is not None
    assert decision.input_tokens == 10
    assert captured["authorization"] == "Bearer secret-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert "data:image/png;base64,aQ==" in str(messages)


def test_adapter_performs_one_controlled_repair() -> None:
    responses = iter(["not-json", '{"type":"finish","message":"done"}'])
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": next(responses)}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(config(), client=client)
    decision = asyncio.run(
        adapter.decide(Task(instruction="finish"), observation(), AgentContext(task_id="task"))
    )
    asyncio.run(client.aclose())

    assert isinstance(decision.action, FinishAction)
    assert requests == 2


def test_adapter_stops_after_configured_repair_limit() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "invalid"}}]},
            )
        )
    )
    adapter = OpenAICompatibleAdapter(config(repair_attempts=0), client=client)

    with pytest.raises(ModelResponseError):
        asyncio.run(
            adapter.decide(Task(instruction="finish"), observation(), AgentContext(task_id="task"))
        )
    asyncio.run(client.aclose())


def test_http_errors_are_translated_without_response_body_leak() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="private upstream response")
        )
    )
    adapter = OpenAICompatibleAdapter(config(), client=client)

    with pytest.raises(ModelConnectionError, match="HTTP 401") as raised:
        asyncio.run(
            adapter.decide(Task(instruction="finish"), observation(), AgentContext(task_id="task"))
        )
    asyncio.run(client.aclose())

    assert "private upstream response" not in str(raised.value)


def test_healthcheck_reports_model_inventory() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "vision-model"}]})
        )
    )
    adapter = OpenAICompatibleAdapter(config(), client=client)

    health = asyncio.run(adapter.healthcheck())
    asyncio.run(client.aclose())

    assert health.connected
    assert health.metadata["available_models"] == 1


def test_image_input_check_sends_image_and_accepts_valid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "vlmux.models.openai_compatible._build_vision_probe",
        lambda: ("data:image/png;base64,probe", "purple"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "purple"}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(config(), client=client)

    support = asyncio.run(adapter.check_image_input())
    asyncio.run(client.aclose())

    assert support.accepted
    assert "data:image/png;base64,probe" in str(captured["payload"])


def test_image_input_check_rejects_incorrect_visual_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vlmux.models.openai_compatible._build_vision_probe",
        lambda: ("data:image/png;base64,probe", "purple"),
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "orange"}}]},
            )
        )
    )
    adapter = OpenAICompatibleAdapter(config(), client=client)

    support = asyncio.run(adapter.check_image_input())
    asyncio.run(client.aclose())

    assert not support.accepted
    assert "did not correctly interpret" in support.detail


def test_image_input_check_rejects_model_http_error_without_leaking_body() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, text="private provider details")
        )
    )
    adapter = OpenAICompatibleAdapter(config(), client=client)

    support = asyncio.run(adapter.check_image_input())
    asyncio.run(client.aclose())

    assert not support.accepted
    assert "HTTP 400" in support.detail
    assert "private provider details" not in support.detail
