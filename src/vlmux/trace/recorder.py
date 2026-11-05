"""Task trace recording for replay and debugging.

Traces are opt-in: only written when a recorder is attached. Screenshots may
contain secrets, so storage location and retention are caller-controlled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vlmux.core import ActionResult, ModelDecision, Observation, Task
from vlmux.events import EventBus


class TraceRecorder:
    """Write task, step, and event records to a run directory."""

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._events_path = self._directory / "events.jsonl"
        self._shots_dir = self._directory / "screenshots"
        self._shots_dir.mkdir(parents=True, exist_ok=True)
        self._step = 0

    @property
    def directory(self) -> Path:
        """Return the run directory for this trace."""
        return self._directory

    async def record_task(self, task: Task) -> None:
        """Write the task definition."""
        payload = task.model_dump(mode="json")
        (self._directory / "task.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def record_step(
        self,
        *,
        task: Task,
        observation: Observation,
        decision: ModelDecision,
        result: ActionResult | None,
    ) -> None:
        """Persist screenshot bytes and one step record."""
        self._step += 1
        import base64

        image_bytes = base64.b64decode(observation.screen.image)
        extension = "jpg" if observation.screen.image_format == "jpeg" else "png"
        shot_path = self._shots_dir / f"{self._step:03d}.{extension}"
        shot_path.write_bytes(image_bytes)
        record: dict[str, Any] = {
            "step": self._step,
            "timestamp": datetime.now(UTC).isoformat(),
            "observation_id": observation.id,
            "screenshot": shot_path.name,
            "decision": decision.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result else None,
        }
        with (self._directory / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    async def record_event(self, event_name: str, **data: Any) -> None:
        """Append one runtime event."""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event_name,
            "data": data,
        }
        with self._events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def attach(self, events: EventBus) -> Any:
        """Subscribe this recorder to an event bus."""

        async def handler(event: Any) -> None:
            await self.record_event(event.name, **event.data)

        unsubscribe = events.subscribe(handler)
        return unsubscribe


def load_trace_events(directory: Path | str) -> list[dict[str, Any]]:
    """Read events recorded by a :class:`TraceRecorder`."""
    path = Path(directory) / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def load_trace_steps(directory: Path | str) -> list[dict[str, Any]]:
    """Read step records recorded by a :class:`TraceRecorder`."""
    path = Path(directory) / "steps.jsonl"
    if not path.exists():
        return []
    steps: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            steps.append(json.loads(line))
    return steps
