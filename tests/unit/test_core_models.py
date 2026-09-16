"""Tests for provider-independent VLMux domain models."""

import pytest
from pydantic import ValidationError

from vlmux.core import (
    ActionResult,
    AgentContext,
    ModelDecision,
    Observation,
    RuntimeResult,
    RuntimeStatus,
    ScreenObservation,
    Task,
)
from vlmux.protocol import ClickAction, FinishAction


def test_task_normalizes_instruction_and_generates_id() -> None:
    task = Task(instruction="  Open Calculator  ")

    assert task.instruction == "Open Calculator"
    assert task.id.startswith("task_")


def test_blank_task_is_invalid() -> None:
    with pytest.raises(ValidationError, match="blank"):
        Task(instruction="   ")


def test_screen_rejects_invalid_base64_and_partial_source_dimensions() -> None:
    with pytest.raises(ValidationError, match="base64"):
        ScreenObservation(width=10, height=10, image="not base64!")
    with pytest.raises(ValidationError, match="provided together"):
        ScreenObservation(width=10, height=10, image="aQ==", source_width=20)


def test_observation_round_trip_preserves_typed_screen() -> None:
    observation = Observation(screen=ScreenObservation(width=10, height=10, image="aQ=="))
    restored = Observation.model_validate_json(observation.model_dump_json())

    assert restored == observation
    assert restored.id.startswith("obs_")


def test_action_result_enforces_consistent_outcome() -> None:
    with pytest.raises(ValidationError, match="cannot contain an error"):
        ActionResult(success=True, duration_ms=1, error="impossible")
    with pytest.raises(ValidationError, match="must contain an error"):
        ActionResult(success=False, duration_ms=1)


def test_agent_context_records_and_bounds_recent_history() -> None:
    context = AgentContext(task_id="task_1", max_recent_steps=2)
    for coordinate in range(3):
        decision = ModelDecision(action=ClickAction(x=coordinate, y=coordinate))
        context.record(
            observation_id=f"obs_{coordinate}",
            decision=decision,
            result=ActionResult(success=True, duration_ms=1),
        )

    assert [step.step for step in context.steps] == [2, 3]
    assert [step.observation_id for step in context.steps] == ["obs_1", "obs_2"]


def test_runtime_result_serializes_terminal_action() -> None:
    result = RuntimeResult(
        task_id="task_1",
        status=RuntimeStatus.SUCCEEDED,
        steps=1,
        duration_ms=10,
        final_action=FinishAction(message="complete"),
    )

    restored = RuntimeResult.model_validate_json(result.model_dump_json())
    assert restored.status is RuntimeStatus.SUCCEEDED
    assert isinstance(restored.final_action, FinishAction)
