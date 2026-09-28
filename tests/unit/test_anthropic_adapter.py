"""Tests for the native Anthropic Messages multimodal adapter."""

import asyncio
import json

import httpx
import pytest

from vlmux.core import AgentContext, Observation, ScreenObservation, Task
from vlmux.exceptions import ModelConnectionError
from vlmux.models import AdapterConfig, AnthropicAdapter
from vlmux.protocol import ClickAction


def config() -> AdapterConfig:
    return AdapterConfig(
        provider="anthropic",
        model="claude-vision-model",
        api_key="secret-key",
        base_url="https://api.anthropic.com",
        request_retries=0,
    )


def observation() -> Observation:
    return Observation(screen=ScreenObservation(width=2, height=2, image="aQ=="))


def test_anthropic_adapter_sends_native_image_block_and_parses_action() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"type":"click","x":1,"y":1}'}],
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicAdapter(config(), client=client)
    decision = asyncio.run(
        adapter.decide(Task(instruction="click"), observation(), AgentContext(task_id="task"))
    )
    asyncio.run(client.aclose())

    assert isinstance(decision.action, ClickAction)
    assert decision.input_tokens == 12
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-api-key"] == "secret-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers
    assert "aQ==" in str(captured["payload"])


def test_anthropic_adapter_repairs_invalid_output() -> None:
    responses = iter(
        [
            {"content": [{"type": "text", "text": "invalid"}]},
            {"content": [{"type": "text", "text": '{"type":"finish","message":"done"}'}]},
        ]
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=next(responses)))
    )
    adapter = AnthropicAdapter(config(), client=client)

    decision = asyncio.run(
        adapter.decide(Task(instruction="finish"), observation(), AgentContext(task_id="task"))
    )
    asyncio.run(client.aclose())

    assert decision.action.type == "finish"


def test_anthropic_http_error_does_not_leak_response_body() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="private provider details")
        )
    )
    adapter = AnthropicAdapter(config(), client=client)

    with pytest.raises(ModelConnectionError, match="HTTP 401") as raised:
        asyncio.run(
            adapter.decide(Task(instruction="finish"), observation(), AgentContext(task_id="task"))
        )
    asyncio.run(client.aclose())

    assert "private provider details" not in str(raised.value)
