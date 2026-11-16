"""Shipped benchmark specs must always parse against the spec model."""

from pathlib import Path

from vlmux.benchmark.runner import discover_specs
from vlmux.benchmark.spec import BenchmarkSpec

BENCHMARKS_DIR = Path(__file__).resolve().parents[2] / "benchmarks"


def test_shipped_benchmark_specs_load() -> None:
    specs = discover_specs(BENCHMARKS_DIR)

    assert specs, "benchmarks directory should not be empty"
    for spec in specs:
        assert isinstance(spec, BenchmarkSpec)
        assert spec.task.strip()


def test_shipped_verifier_types_are_known() -> None:
    specs = discover_specs(BENCHMARKS_DIR)

    known = {
        "screen_contains_text",
        "url_equals",
        "window_exists",
        "dom_contains_text",
        "always_true",
    }
    for spec in specs:
        assert spec.success.type in known


def test_every_shipped_spec_declares_success() -> None:
    for spec in discover_specs(BENCHMARKS_DIR):
        assert spec.success.type, f"{spec.name} is missing a success verifier"
