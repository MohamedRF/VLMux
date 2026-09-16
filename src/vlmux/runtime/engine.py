"""SEE → DECIDE → VALIDATE → ACT runtime orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from vlmux.core import (
    ActionResult,
    AgentContext,
    RuntimeResult,
    RuntimeStatus,
    Task,
)
from vlmux.events import EventBus
from vlmux.exceptions import (
    ActionValidationError,
    ModelConnectionError,
    ModelResponseError,
    ScreenCaptureError,
)
from vlmux.executors import ComputerExecutor
from vlmux.models import ModelAdapter
from vlmux.observation import Observer
from vlmux.policy import PolicyDecision, PolicyEngine, PolicyOutcome
from vlmux.protocol import Action, FailAction, FinishAction, ScreenshotAction
from vlmux.protocol.validation import validate_action_coordinates

ConfirmationHandler = Callable[[Action, PolicyDecision], Awaitable[bool]]


@dataclass(slots=True)
class _RuntimeProgress:
    steps: int = 0


class RuntimeConfig(BaseModel):
    """Hard limits that prevent uncontrolled runtime loops."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(default=50, ge=1, le=10_000)
    max_runtime_seconds: float = Field(default=300.0, gt=0, le=86_400)
    max_failures: int = Field(default=3, ge=1, le=100)
    dry_run: bool = False


class Runtime:
    """Coordinate injected model, observer, policy, and executor components."""

    def __init__(
        self,
        *,
        model: ModelAdapter,
        observer: Observer,
        executor: ComputerExecutor | None,
        policy: PolicyEngine | None = None,
        events: EventBus | None = None,
        confirmation_handler: ConfirmationHandler | None = None,
        config: RuntimeConfig | None = None,
    ) -> None:
        self._model = model
        self._observer = observer
        self._executor = executor
        self._policy = policy or PolicyEngine()
        self._events = events or EventBus()
        self._confirmation_handler = confirmation_handler
        self._config = config or RuntimeConfig()

    async def run(self, task: Task | str) -> RuntimeResult:
        runtime_task = Task(instruction=task) if isinstance(task, str) else task
        started = perf_counter()
        progress = _RuntimeProgress()
        await self._events.emit("task.started", task_id=runtime_task.id)
        try:
            async with asyncio.timeout(self._config.max_runtime_seconds):
                return await self._run_loop(runtime_task, started, progress)
        except TimeoutError:
            await self._events.emit("task.failed", task_id=runtime_task.id, reason="timeout")
            return RuntimeResult(
                task_id=runtime_task.id,
                status=RuntimeStatus.TIMED_OUT,
                steps=progress.steps,
                duration_ms=(perf_counter() - started) * 1000,
                message="maximum runtime exceeded",
            )

    async def _run_loop(
        self,
        task: Task,
        started: float,
        progress: _RuntimeProgress,
    ) -> RuntimeResult:
        context = AgentContext(task_id=task.id)
        failures = 0
        for step in range(1, self._config.max_steps + 1):
            progress.steps = step
            try:
                observation = await self._observer.capture()
            except ScreenCaptureError as error:
                return await self._failed(task, step - 1, started, str(error))
            await self._events.emit(
                "observation.created",
                task_id=task.id,
                step=step,
                observation_id=observation.id,
            )
            await self._events.emit("model.requested", task_id=task.id, step=step)
            try:
                decision = await self._model.decide(task, observation, context)
            except (ModelConnectionError, ModelResponseError) as error:
                failures += 1
                await self._events.emit(
                    "model.failed",
                    task_id=task.id,
                    step=step,
                    error=str(error),
                )
                if failures >= self._config.max_failures:
                    return await self._failed(task, step, started, str(error))
                continue

            action = decision.action
            await self._events.emit(
                "model.responded",
                task_id=task.id,
                step=step,
                decision_id=decision.id,
            )
            try:
                validate_action_coordinates(action, observation.screen)
            except ActionValidationError as error:
                return await self._failed(task, step, started, str(error), action)
            await self._events.emit(
                "action.proposed",
                task_id=task.id,
                step=step,
                action_type=action.type,
            )
            policy_decision = await self._policy.evaluate(action)
            if policy_decision.outcome is PolicyOutcome.DENY:
                await self._events.emit(
                    "action.rejected",
                    task_id=task.id,
                    step=step,
                    reason=policy_decision.reason,
                )
                return await self._failed(task, step, started, policy_decision.reason, action)
            if (
                policy_decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
                and not self._config.dry_run
            ):
                approved = (
                    await self._confirmation_handler(action, policy_decision)
                    if self._confirmation_handler is not None
                    else False
                )
                if not approved:
                    await self._events.emit(
                        "action.rejected",
                        task_id=task.id,
                        step=step,
                        reason="confirmation denied",
                    )
                    return await self._failed(
                        task,
                        step,
                        started,
                        "action was not confirmed",
                        action,
                    )
            await self._events.emit(
                "action.approved",
                task_id=task.id,
                step=step,
                action_type=action.type,
            )

            if self._config.dry_run:
                context.record(observation_id=observation.id, decision=decision)
                await self._events.emit(
                    "task.completed",
                    task_id=task.id,
                    status=RuntimeStatus.DRY_RUN.value,
                )
                return self._result(
                    task,
                    RuntimeStatus.DRY_RUN,
                    step,
                    started,
                    "dry run proposed one validated action",
                    action,
                )

            if isinstance(action, FinishAction):
                result = ActionResult(action_id=action.id, success=True, duration_ms=0)
                context.record(
                    observation_id=observation.id,
                    decision=decision,
                    result=result,
                )
                await self._events.emit("task.completed", task_id=task.id, steps=step)
                return self._result(
                    task,
                    RuntimeStatus.SUCCEEDED,
                    step,
                    started,
                    action.message or "task completed",
                    action,
                )
            if isinstance(action, FailAction):
                return await self._failed(task, step, started, action.reason, action)

            if isinstance(action, ScreenshotAction):
                result = ActionResult(action_id=action.id, success=True, duration_ms=0)
            elif self._executor is None:
                return await self._failed(
                    task,
                    step,
                    started,
                    "no desktop executor is available",
                    action,
                )
            else:
                result = await self._executor.execute(action)
            context.record(
                observation_id=observation.id,
                decision=decision,
                result=result,
            )
            await self._events.emit(
                "action.executed" if result.success else "action.failed",
                task_id=task.id,
                step=step,
                action_type=action.type,
                error=result.error,
            )
            await self._events.emit(
                "step.completed",
                task_id=task.id,
                step=step,
                success=result.success,
            )
            if result.success:
                failures = 0
            else:
                failures += 1
                if failures >= self._config.max_failures:
                    return await self._failed(
                        task,
                        step,
                        started,
                        result.error or "action execution failed",
                        action,
                    )

        await self._events.emit("task.failed", task_id=task.id, reason="max_steps")
        return self._result(
            task,
            RuntimeStatus.MAX_STEPS_EXCEEDED,
            self._config.max_steps,
            started,
            "maximum steps exceeded",
        )

    async def _failed(
        self,
        task: Task,
        steps: int,
        started: float,
        message: str,
        final_action: Action | None = None,
    ) -> RuntimeResult:
        await self._events.emit("task.failed", task_id=task.id, reason=message)
        return self._result(
            task,
            RuntimeStatus.FAILED,
            steps,
            started,
            message,
            final_action,
        )

    @staticmethod
    def _result(
        task: Task,
        status: RuntimeStatus,
        steps: int,
        started: float,
        message: str,
        final_action: Action | None = None,
    ) -> RuntimeResult:
        return RuntimeResult(
            task_id=task.id,
            status=status,
            steps=steps,
            duration_ms=(perf_counter() - started) * 1000,
            message=message,
            final_action=final_action,
        )
