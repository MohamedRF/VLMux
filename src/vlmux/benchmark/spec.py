"""Benchmark task specifications and success verifiers.

Specs are TOML (matching VLMux configuration style) with an extensible
verifier union. The runner executes the same tasks against different models
and reports raw reproducible measurements, never fabricated rankings.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerifierSpec(BaseModel):
    """One success condition evaluated against the final observation."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "screen_contains_text",
        "url_equals",
        "window_exists",
        "dom_contains_text",
        "always_true",
    ]
    value: str = ""


class BenchmarkSpec(BaseModel):
    """A single reproducible benchmark task."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    task: str = Field(min_length=1)
    success: VerifierSpec
    max_steps: int = Field(default=20, ge=1, le=10_000)

    @model_validator(mode="after")
    def task_must_not_be_blank(self) -> BenchmarkSpec:
        if not self.task.strip():
            raise ValueError("benchmark task must not be blank")
        return self


def load_benchmark_spec(path: str | Path) -> BenchmarkSpec:
    """Load and validate one benchmark TOML document."""
    document = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkSpec.model_validate(document)


class SpecVerifier:
    """Evaluate a :class:`VerifierSpec` against final observation metadata.

    Accepts either an :class:`~vlmux.core.Observation` instance or its
    ``model_dump(mode="json")`` mapping (as carried in runtime metadata).
    """

    def __init__(self, spec: VerifierSpec) -> None:
        self._spec = spec

    @staticmethod
    def _field(observation: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(observation, Mapping):
            return observation.get(field_name, default)
        return getattr(observation, field_name, default)

    def verify_observation(self, observation: Any) -> bool:
        """Check the success condition using observation metadata."""

        spec = self._spec
        if spec.type == "always_true":
            return True
        metadata = self._field(observation, "metadata", {}) or {}
        if spec.type == "url_equals":
            url = str(metadata.get("browser_url", ""))
            return url == spec.value
        if spec.type == "screen_contains_text":
            text = str(metadata.get("ocr_text", ""))
            return spec.value in text
        if spec.type == "window_exists":
            windows = self._field(observation, "windows", []) or []
            titles = [
                str(
                    window.get("title", "")
                    if isinstance(window, Mapping)
                    else getattr(window, "title", "")
                )
                for window in windows
            ]
            return any(spec.value in title for title in titles)
        if spec.type == "dom_contains_text":
            dom = self._field(observation, "dom", {}) or {}
            html = str(dom.get("html", "")) if isinstance(dom, Mapping) else ""
            return spec.value in html
        return False
