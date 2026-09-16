"""Core domain models shared across adapters, runtime, and executors."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vlmux.protocol.actions import Action


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class DomainModel(BaseModel):
    """Strict base class for provider-independent domain values."""

    model_config = ConfigDict(extra="forbid")


class PerceptionMode(StrEnum):
    """Standardized sources from which an observation can be assembled."""

    RAW = "raw"
    OCR = "ocr"
    A11Y = "a11y"
    DOM = "dom"
    SET_OF_MARKS = "set_of_marks"
    HYBRID = "hybrid"


class Task(DomainModel):
    """A user request to be completed by the runtime."""

    id: str = Field(default_factory=lambda: _identifier("task"), min_length=1)
    instruction: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("instruction must not be blank")
        return value


class CursorState(DomainModel):
    """Cursor coordinates in the source screen coordinate system."""

    x: int
    y: int
    visible: bool = True


class WindowInfo(DomainModel):
    """Portable metadata describing a desktop window."""

    id: str | None = None
    title: str = ""
    application: str | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    focused: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScreenObservation(DomainModel):
    """A captured screen encoded for transport to a vision model.

    ``source_width`` and ``source_height`` preserve the native coordinate
    space when the encoded image has been resized.
    """

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image: str = Field(min_length=1, description="Base64-encoded image bytes")
    image_format: str = Field(default="png", pattern=r"^[a-z0-9][a-z0-9.+-]*$")
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)
    origin_x: int = 0
    origin_y: int = 0
    monitor: int | None = Field(default=None, ge=0)

    @field_validator("image")
    @classmethod
    def image_must_be_valid_base64(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("image must contain valid base64") from error
        return value

    @model_validator(mode="after")
    def source_dimensions_must_be_complete(self) -> Self:
        if (self.source_width is None) != (self.source_height is None):
            raise ValueError("source_width and source_height must be provided together")
        return self


class Observation(DomainModel):
    """A provider-independent snapshot of observable computer state."""

    id: str = Field(default_factory=lambda: _identifier("obs"), min_length=1)
    timestamp: datetime = Field(default_factory=_utc_now)
    mode: PerceptionMode = PerceptionMode.RAW
    screen: ScreenObservation
    cursor: CursorState | None = None
    active_window: WindowInfo | None = None
    windows: list[WindowInfo] = Field(default_factory=list)
    ocr: list[dict[str, Any]] = Field(default_factory=list)
    accessibility: dict[str, Any] | None = None
    dom: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(DomainModel):
    """The observed outcome of one attempted action."""

    id: str = Field(default_factory=lambda: _identifier("result"), min_length=1)
    action_id: str | None = None
    success: bool
    duration_ms: float = Field(ge=0)
    error: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def outcome_must_be_consistent(self) -> Self:
        if self.success and self.error is not None:
            raise ValueError("a successful action result cannot contain an error")
        if not self.success and (self.error is None or not self.error.strip()):
            raise ValueError("a failed action result must contain an error")
        return self


class ModelDecision(DomainModel):
    """A validated model decision containing exactly one VAP action."""

    id: str = Field(default_factory=lambda: _identifier("decision"), min_length=1)
    action: Action
    reasoning: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepRecord(DomainModel):
    """Concise history for a completed runtime step."""

    step: int = Field(ge=1)
    observation_id: str = Field(min_length=1)
    decision: ModelDecision
    result: ActionResult | None = None
    timestamp: datetime = Field(default_factory=_utc_now)


class AgentContext(DomainModel):
    """Bounded action history and important state supplied to a model."""

    task_id: str = Field(min_length=1)
    steps: list[StepRecord] = Field(default_factory=list)
    max_recent_steps: int = Field(default=20, ge=1, le=1000)
    important_state: dict[str, Any] = Field(default_factory=dict)

    def record(
        self,
        *,
        observation_id: str,
        decision: ModelDecision,
        result: ActionResult | None = None,
    ) -> StepRecord:
        """Append a step and evict old history beyond the configured bound."""
        record = StepRecord(
            step=(self.steps[-1].step + 1) if self.steps else 1,
            observation_id=observation_id,
            decision=decision,
            result=result,
        )
        self.steps.append(record)
        if len(self.steps) > self.max_recent_steps:
            del self.steps[: -self.max_recent_steps]
        return record


class RuntimeStatus(StrEnum):
    """Terminal states returned by the VLMux runtime."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    TIMED_OUT = "timed_out"
    DRY_RUN = "dry_run"


class RuntimeResult(DomainModel):
    """Structured terminal result of a VLMux task run."""

    task_id: str = Field(min_length=1)
    status: RuntimeStatus
    steps: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    message: str | None = None
    final_action: Action | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
