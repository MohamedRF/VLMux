"""Tests for MCP tools, trace recording, and benchmark primitives."""

from __future__ import annotations

import asyncio
from pathlib import Path

from vlmux.benchmark import (
    BenchmarkSpec,
    SpecVerifier,
    VerifierSpec,
    estimate_cost,
    format_report,
)
from vlmux.benchmark.runner import BenchmarkResult
from vlmux.core import ActionResult, ModelDecision, Observation, ScreenObservation, Task
from vlmux.events import EventBus
from vlmux.mcp.server import TOOLS, MCPServer
from vlmux.trace import TraceRecorder, load_trace_events, load_trace_steps


def test_mcp_tool_catalog_contains_spec_tools() -> None:
    names = {tool["name"] for tool in TOOLS}
    for expected in (
        "computer.observe",
        "computer.screenshot",
        "computer.click",
        "computer.double_click",
        "computer.type",
        "computer.hotkey",
        "computer.scroll",
        "computer.drag",
        "computer.wait",
        "computer.windows",
        "computer.open_app",
        "computer.run_task",
    ):
        assert expected in names


def test_mcp_initialize_and_tools_list() -> None:
    server = MCPServer.__new__(MCPServer)
    init = asyncio.run(
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    )
    assert init is not None and init["result"]["serverInfo"]["name"] == "vlmux-mcp"
    listed = asyncio.run(server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    assert listed is not None
    assert len(listed["result"]["tools"]) == len(TOOLS)


def test_trace_recorder_writes_steps_and_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        recorder = TraceRecorder(tmp_path / "run1")
        task = Task(instruction="do thing")
        await recorder.record_task(task)
        screen = ScreenObservation(width=1, height=1, image="aQ==")
        observation = Observation(screen=screen)
        decision = ModelDecision(action={"type": "finish"})
        result = ActionResult(success=True, duration_ms=1)
        await recorder.record_step(
            task=task, observation=observation, decision=decision, result=result
        )
        events = EventBus()
        recorder.attach(events)
        await events.emit("task.completed", task_id=task.id)
        steps = load_trace_steps(tmp_path / "run1")
        recorded_events = load_trace_events(tmp_path / "run1")
        assert len(steps) == 1
        assert steps[0]["observation_id"] == observation.id
        assert (tmp_path / "run1" / "screenshots" / "001.png").exists()
        assert any(event["event"] == "task.completed" for event in recorded_events)

    asyncio.run(scenario())


def test_benchmark_spec_and_verifiers() -> None:
    spec = BenchmarkSpec(
        name="calc",
        task="Open Calculator",
        success=VerifierSpec(type="always_true"),
    )
    assert spec.max_steps == 20
    assert SpecVerifier(spec.success).verify_observation(None) is True
    url_verifier = SpecVerifier(VerifierSpec(type="url_equals", value="https://example.com/"))
    observation = Observation(
        screen=ScreenObservation(width=1, height=1, image="aQ=="),
        metadata={"browser_url": "https://example.com/"},
    )
    assert url_verifier.verify_observation(observation) is True


def test_cost_estimates() -> None:
    assert estimate_cost("ollama/qwen3-vl", 100, 50) == "local"
    assert estimate_cost("vllm/model", 100, 50) == "local"
    assert estimate_cost("openrouter/model", 100, 50) == "unknown"
    assert (
        estimate_cost("openai/model", 1000, 1000, input_price_per_1k=1.0, output_price_per_1k=2.0)
        == "$3.0000"
    )


def test_format_report_renders_rows() -> None:
    results = [
        BenchmarkResult(
            spec_name="calc",
            model="ollama/qwen3-vl",
            success=True,
            steps=7,
            latency_ms=11200,
            input_tokens=1000,
            output_tokens=500,
            cost="local",
            status="succeeded",
        )
    ]
    report = format_report(results)
    assert "ollama/qwen3-vl" in report
    assert "local" in report
