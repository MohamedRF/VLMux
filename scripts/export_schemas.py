"""Export stable JSON Schema artifacts for VAP and core domain models."""

from __future__ import annotations

import json
import re
from pathlib import Path

from vlmux.core import (
    ActionResult,
    AgentContext,
    CursorState,
    ModelDecision,
    Observation,
    RuntimeResult,
    ScreenObservation,
    StepRecord,
    Task,
    WindowInfo,
)
from vlmux.protocol import action_json_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = ROOT / "schemas"
CORE_MODELS = (
    Task,
    CursorState,
    WindowInfo,
    ScreenObservation,
    Observation,
    ActionResult,
    ModelDecision,
    StepRecord,
    AgentContext,
    RuntimeResult,
)


def _write_schema(path: Path, schema: dict[str, object]) -> None:
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _schema_filename(model_name: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", "-", model_name).lower()
    return f"{words}.schema.json"


def main() -> None:
    """Write deterministic schema documents to the repository schema directory."""
    SCHEMA_DIRECTORY.mkdir(exist_ok=True)
    _write_schema(SCHEMA_DIRECTORY / "vap-action.schema.json", action_json_schema())
    for model in CORE_MODELS:
        _write_schema(
            SCHEMA_DIRECTORY / _schema_filename(model.__name__), model.model_json_schema()
        )


if __name__ == "__main__":
    main()
