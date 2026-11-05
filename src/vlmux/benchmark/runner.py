"""Benchmark runner: execute specs and report raw measurements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from vlmux.benchmark.spec import BenchmarkSpec, SpecVerifier, load_benchmark_spec
from vlmux.core import RuntimeStatus


@dataclass(slots=True)
class BenchmarkResult:
    """Raw measurement for one (spec, model) pair."""

    spec_name: str
    model: str
    success: bool
    steps: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost: str
    status: str


def is_local_model(model_reference: str) -> bool:
    """Return True when the model reference denotes a local provider."""
    provider = model_reference.split("/", 1)[0].casefold()
    return provider in {"ollama", "vllm", "llamacpp", "llama.cpp"}


def estimate_cost(
    model_reference: str,
    input_tokens: int,
    output_tokens: int,
    *,
    input_price_per_1k: float | None = None,
    output_price_per_1k: float | None = None,
) -> str:
    """Return ``local``, an estimated dollar cost, or ``unknown``."""
    if is_local_model(model_reference):
        return "local"
    if input_price_per_1k is None or output_price_per_1k is None:
        return "unknown"
    cost = (input_tokens / 1000) * input_price_per_1k + (output_tokens / 1000) * output_price_per_1k
    return f"${cost:.4f}"


class BenchmarkRunner:
    """Run one benchmark spec against one model through the runtime."""

    def __init__(self, run_task: Any) -> None:
        self._run_task = run_task

    async def run_one(
        self,
        spec: BenchmarkSpec,
        model_reference: str,
        *,
        input_price_per_1k: float | None = None,
        output_price_per_1k: float | None = None,
    ) -> BenchmarkResult:
        """Execute one spec and convert the runtime result into a measurement."""
        started = perf_counter()
        result = await self._run_task(spec.task, model_reference, spec.max_steps)
        latency_ms = (perf_counter() - started) * 1000
        usage = result.metadata.get("usage", {}) if isinstance(result.metadata, dict) else {}
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        success = result.status is RuntimeStatus.SUCCEEDED
        if success and spec.success.type != "always_true":
            final_observation = result.metadata.get("_final_observation")
            if final_observation is not None:
                success = SpecVerifier(spec.success).verify_observation(final_observation)
        cost = estimate_cost(
            model_reference,
            input_tokens,
            output_tokens,
            input_price_per_1k=input_price_per_1k,
            output_price_per_1k=output_price_per_1k,
        )
        return BenchmarkResult(
            spec_name=spec.name,
            model=model_reference,
            success=success,
            steps=result.steps,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            status=result.status.value,
        )


def discover_specs(directory: str | Path) -> list[BenchmarkSpec]:
    """Load every ``*.toml`` benchmark spec in a directory."""
    base = Path(directory)
    if not base.exists():
        raise FileNotFoundError(f"benchmark directory not found: {base}")
    specs: list[BenchmarkSpec] = []
    for path in sorted(base.glob("*.toml")):
        specs.append(load_benchmark_spec(path))
    return specs


def format_report(results: list[BenchmarkResult]) -> str:
    """Render raw measurements as an aligned table."""
    if not results:
        return "No benchmark results."
    header = f"{'Model':<28} {'Success':<8} {'Steps':>6} {'Latency':>10} {'Cost':>10}"
    lines = [header, "-" * len(header)]
    for result in results:
        lines.append(
            f"{result.model:<28} {'yes' if result.success else 'no':<8} "
            f"{result.steps:>6} {result.latency_ms / 1000:>8.2f}s {result.cost:>10}"
        )
    return "\n".join(lines)
