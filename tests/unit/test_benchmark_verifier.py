"""Benchmark runner/verifier: the final observation must reach the verifier."""

from __future__ import annotations

import asyncio

from vlmux.benchmark.runner import BenchmarkRunner, discover_specs
from vlmux.benchmark.spec import BenchmarkSpec, SpecVerifier, VerifierSpec
from vlmux.core import RuntimeResult, RuntimeStatus


def _observation(**metadata):
    merged = {"ocr_text": "hello world", "browser_url": "https://example.com/a", **metadata}
    return {
        "metadata": merged,
        "windows": [{"title": "Calculator"}],
        "dom": {"html": "<html>submit order</html>"},
    }


def test_screen_contains_text_verifier_with_dict_observation() -> None:
    verifier = SpecVerifier(VerifierSpec(type="screen_contains_text", value="hello"))

    assert verifier.verify_observation(_observation()) is True
    missing = SpecVerifier(VerifierSpec(type="screen_contains_text", value="missing"))
    assert missing.verify_observation(_observation()) is False


def test_url_equals_verifier() -> None:
    hit = SpecVerifier(VerifierSpec(type="url_equals", value="https://example.com/a"))
    miss = SpecVerifier(VerifierSpec(type="url_equals", value="https://other.example.com"))
    assert hit.verify_observation(_observation())
    assert not miss.verify_observation(_observation())


def test_window_exists_verifier() -> None:
    hit = SpecVerifier(VerifierSpec(type="window_exists", value="Calc"))
    miss = SpecVerifier(VerifierSpec(type="window_exists", value="Terminal"))
    assert hit.verify_observation(_observation())
    assert not miss.verify_observation(_observation())


def test_dom_contains_text_verifier() -> None:
    verifier = SpecVerifier(VerifierSpec(type="dom_contains_text", value="submit order"))
    assert verifier.verify_observation(_observation())


def _result(**metadata) -> RuntimeResult:
    return RuntimeResult(
        task_id="task_1",
        status=RuntimeStatus.SUCCEEDED,
        steps=3,
        duration_ms=1.0,
        message="done",
        metadata={"usage": {"input_tokens": 10, "output_tokens": 5}, **metadata},
    )


def test_runner_applies_verifier_to_final_observation() -> None:
    async def fake_run_task(instruction, model, max_steps):
        return _result(_final_observation=_observation())

    runner = BenchmarkRunner(fake_run_task)
    spec = BenchmarkSpec(
        name="verify",
        task="do it",
        success=VerifierSpec(type="screen_contains_text", value="hello"),
    )
    result = asyncio.run(runner.run_one(spec, "ollama/qwen3-vl"))

    assert result.success is True
    assert result.input_tokens == 10
    assert result.output_tokens == 5


def test_runner_fails_when_verifier_rejects() -> None:
    async def fake_run_task(instruction, model, max_steps):
        return _result(_final_observation=_observation(ocr_text="nope"))

    runner = BenchmarkRunner(fake_run_task)
    spec = BenchmarkSpec(
        name="verify",
        task="do it",
        success=VerifierSpec(type="screen_contains_text", value="hello"),
    )
    result = asyncio.run(runner.run_one(spec, "ollama/qwen3-vl"))

    assert result.success is False


def test_runner_fails_honestly_when_observation_missing() -> None:
    async def fake_run_task(instruction, model, max_steps):
        return _result()  # no _final_observation attached

    runner = BenchmarkRunner(fake_run_task)
    spec = BenchmarkSpec(
        name="verify",
        task="do it",
        success=VerifierSpec(type="screen_contains_text", value="hello"),
    )
    result = asyncio.run(runner.run_one(spec, "ollama/qwen3-vl"))

    assert result.success is False


def test_runner_tolerates_malformed_usage_counts() -> None:
    async def fake_run_task(instruction, model, max_steps):
        return RuntimeResult(
            task_id="task_1",
            status=RuntimeStatus.SUCCEEDED,
            steps=1,
            duration_ms=1.0,
            metadata={
                "usage": {"input_tokens": None, "output_tokens": "not-a-number"},
                "_final_observation": _observation(),
            },
        )

    runner = BenchmarkRunner(fake_run_task)
    spec = BenchmarkSpec(name="verify", task="do it", success=VerifierSpec(type="always_true"))
    result = asyncio.run(runner.run_one(spec, "ollama/qwen3-vl"))

    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_discover_specs_names_invalid_file(tmp_path) -> None:
    bad = tmp_path / "broken.toml"
    bad.write_text("name = 1", encoding="utf-8")

    try:
        discover_specs(tmp_path)
    except ValueError as error:
        assert "broken.toml" in str(error)
    else:
        raise AssertionError("expected ValueError naming the bad file")
