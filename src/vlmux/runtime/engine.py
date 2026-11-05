"""SEE → DECIDE → VALIDATE → ACT runtime orchestration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from vlmux.core import (
    ActionResult,
    AgentContext,
    Observation,
    RuntimeResult,
    RuntimeStatus,
    Task,
)
from vlmux.events import EventBus
from vlmux.exceptions import (
    ActionExecutionError,
    ActionValidationError,
    ModelConnectionError,
    ModelResponseError,
    ScreenCaptureError,
)
from vlmux.executors import ComputerExecutor
from vlmux.models import ModelAdapter
from vlmux.observation import Observer
from vlmux.perception import resolve_mark
from vlmux.perception.coordinates import image_to_screen_coordinates
from vlmux.policy import PolicyDecision, PolicyEngine, PolicyOutcome
from vlmux.protocol import (
    Action,
    BrowserBackAction,
    BrowserForwardAction,
    BrowserNavigateAction,
    BrowserReloadAction,
    ClickAction,
    ClickMarkAction,
    FailAction,
    FinishAction,
    ScreenshotAction,
    WaitAction,
)
from vlmux.protocol.validation import validate_action_coordinates

ConfirmationHandler = Callable[[Action, PolicyDecision], Awaitable[bool]]

#: Signature types watched for loop detection.
_LOOP_SIGNATURE_TYPES = frozenset({"click", "double_click", "right_click", "scroll"})


class Verifier(Protocol):
    """Check whether a task is actually complete before accepting finish."""

    async def verify(self, task: Task, observation: Observation) -> bool:
        """Return True when the task success condition holds."""
        ...


class StepRecorder(Protocol):
    """Persist one completed step for trace/replay, if configured."""

    async def record_step(
        self, *, task: Task, observation: Observation, decision: Any, result: ActionResult | None
    ) -> None:
        """Record observation, decision, and outcome for one step."""
        ...


def perceptual_hash(screen: Any) -> str:
    """Compute a lightweight perceptual hash for screen-change detection.

    Uses a 16x16 grayscale average hash. Non-image payloads fall back to a
    raw-bytes hash so fakes and synthetic observations degrade gracefully.
    """
    raw = base64.b64decode(screen.image)
    try:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(raw)).convert("L")
        image = image.resize((16, 16))
        pixels = list(image.getdata())
        average = sum(pixels) / len(pixels)
        bits = "".join("1" if pixel > average else "0" for pixel in pixels)
    except Exception:
        bits = hashlib.sha256(raw).hexdigest()
    return hashlib.md5(bits.encode()).hexdigest()[:16]


def screen_hashes_match(previous: str | None, current: str | None) -> bool:
    """Return True when two perceptual hashes are equal and present."""
    return previous is not None and current is not None and previous == current


def action_signature(action: Action) -> str:
    """Return a stable signature used for loop detection."""
    if isinstance(action, ClickMarkAction):
        return f"click_mark:{action.mark}"
    if isinstance(action, (ClickAction,)):
        return f"click:{action.x},{action.y}"
    if action.type in ("double_click", "right_click", "move_cursor"):
        data = action.model_dump()
        return f"{action.type}:{data.get('x')},{data.get('y')}"
    if action.type == "scroll":
        data = action.model_dump()
        return f"scroll:{data.get('delta_x')},{data.get('delta_y')}"
    return action.type


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
    loop_threshold: int = Field(default=5, ge=2, le=100)


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
        browser_executor: Any | None = None,
        verifier: Verifier | None = None,
        recorder: StepRecorder | None = None,
    ) -> None:
        self._model = model
        self._observer = observer
        self._executor = executor
        self._policy = policy or PolicyEngine()
        self._events = events or EventBus()
        self._confirmation_handler = confirmation_handler
        self._config = config or RuntimeConfig()
        self._browser_executor = browser_executor
        self._verifier = verifier
        self._recorder = recorder

    async def run(self, task: Task | str) -> RuntimeResult:
        runtime_task = Task(instruction=task) if isinstance(task, str) else task
        started = perf_counter()
        progress = _RuntimeProgress()
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        await self._events.emit("task.started", task_id=runtime_task.id)
        try:
            async with asyncio.timeout(self._config.max_runtime_seconds):
                return await self._run_loop(runtime_task, started, progress, usage)
        except TimeoutError:
            await self._events.emit("task.failed", task_id=runtime_task.id, reason="timeout")
            return RuntimeResult(
                task_id=runtime_task.id,
                status=RuntimeStatus.TIMED_OUT,
                steps=progress.steps,
                duration_ms=(perf_counter() - started) * 1000,
                message="maximum runtime exceeded",
                metadata={"usage": usage},
            )

    async def _run_loop(
        self,
        task: Task,
        started: float,
        progress: _RuntimeProgress,
        usage: dict[str, int],
    ) -> RuntimeResult:
        context = AgentContext(task_id=task.id)
        failures = 0
        loop_streak = 0
        last_signature = ""
        previous_hash: str | None = None
        for step in range(1, self._config.max_steps + 1):
            progress.steps = step
            try:
                observation = await self._observer.capture()
            except ScreenCaptureError as error:
                return await self._failed(task, step - 1, started, str(error), usage=usage)
            current_hash = perceptual_hash(observation.screen)
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
                    return await self._failed(task, step, started, str(error), usage=usage)
                continue

            if decision.input_tokens is not None:
                usage["input_tokens"] += decision.input_tokens
            if decision.output_tokens is not None:
                usage["output_tokens"] += decision.output_tokens

            action = decision.action
            await self._events.emit(
                "model.responded",
                task_id=task.id,
                step=step,
                decision_id=decision.id,
            )

            # Resolve Set-of-Marks into concrete coordinates before validation.
            if isinstance(action, ClickMarkAction):
                try:
                    mark_x, mark_y = resolve_mark(observation.metadata, action.mark)
                    resolved_x, resolved_y = image_to_screen_coordinates(
                        mark_x, mark_y, observation.screen
                    )
                    action = ClickAction(x=resolved_x, y=resolved_y)
                except ActionValidationError as error:
                    return await self._failed(task, step, started, str(error), usage=usage)

            # Loop detection: same signature repeated consecutively.
            signature = action_signature(action)
            if signature == last_signature and action.type in _LOOP_SIGNATURE_TYPES:
                loop_streak += 1
            else:
                loop_streak = 1
                last_signature = signature
            if loop_streak >= self._config.loop_threshold:
                await self._events.emit(
                    "runtime.loop_detected",
                    task_id=task.id,
                    step=step,
                    signature=signature,
                    streak=loop_streak,
                )
                return await self._failed(
                    task,
                    step,
                    started,
                    f"loop detected: '{signature}' repeated {loop_streak} times",
                    usage=usage,
                )

            try:
                validate_action_coordinates(action, observation.screen)
            except ActionValidationError as error:
                return await self._failed(task, step, started, str(error), action, usage=usage)
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
                return await self._failed(
                    task, step, started, policy_decision.reason, action, usage=usage
                )
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
                        usage=usage,
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
                return RuntimeResult(
                    task_id=task.id,
                    status=RuntimeStatus.DRY_RUN,
                    steps=step,
                    duration_ms=(perf_counter() - started) * 1000,
                    message="dry run proposed one validated action",
                    final_action=action,
                    metadata={"usage": usage},
                )

            if isinstance(action, FinishAction):
                if self._verifier is not None:
                    verified = await self._verifier.verify(task, observation)
                    if not verified:
                        await self._events.emit(
                            "action.rejected",
                            task_id=task.id,
                            step=step,
                            reason="verifier rejected completion claim",
                        )
                        result = ActionResult(
                            action_id=action.id,
                            success=False,
                            duration_ms=0,
                            error="task completion was not verified",
                        )
                        context.record(
                            observation_id=observation.id,
                            decision=decision,
                            result=result,
                        )
                        failures += 1
                        if failures >= self._config.max_failures:
                            return await self._failed(
                                task,
                                step,
                                started,
                                "task completion could not be verified",
                                action,
                                usage=usage,
                            )
                        continue
                result = ActionResult(action_id=action.id, success=True, duration_ms=0)
                context.record(
                    observation_id=observation.id,
                    decision=decision,
                    result=result,
                )
                await self._events.emit("task.completed", task_id=task.id, steps=step)
                return RuntimeResult(
                    task_id=task.id,
                    status=RuntimeStatus.SUCCEEDED,
                    steps=step,
                    duration_ms=(perf_counter() - started) * 1000,
                    message=action.message or "task completed",
                    final_action=action,
                    metadata={"usage": usage},
                )
            if isinstance(action, FailAction):
                return await self._failed(task, step, started, action.reason, action, usage=usage)

            if isinstance(action, ScreenshotAction):
                result = ActionResult(action_id=action.id, success=True, duration_ms=0)
            elif isinstance(
                action,
                (
                    BrowserNavigateAction,
                    BrowserBackAction,
                    BrowserForwardAction,
                    BrowserReloadAction,
                ),
            ):
                result = await self._execute_browser_action(task, step, action)
            elif self._executor is None:
                return await self._failed(
                    task,
                    step,
                    started,
                    "no desktop executor is available",
                    action,
                    usage=usage,
                )
            else:
                result = await self._executor.execute(action)

            # Screen-change check for this step.
            if (
                previous_hash is not None
                and screen_hashes_match(previous_hash, current_hash)
                and not isinstance(action, (ScreenshotAction, WaitAction))
            ):
                await self._events.emit(
                    "runtime.screen_unchanged",
                    task_id=task.id,
                    step=step,
                    action_type=action.type,
                )
            previous_hash = current_hash

            context.record(
                observation_id=observation.id,
                decision=decision,
                result=result,
            )
            if self._recorder is not None:
                await self._recorder.record_step(
                    task=task, observation=observation, decision=decision, result=result
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
                        usage=usage,
                    )

        await self._events.emit("task.failed", task_id=task.id, reason="max_steps")
        return RuntimeResult(
            task_id=task.id,
            status=RuntimeStatus.MAX_STEPS_EXCEEDED,
            steps=self._config.max_steps,
            duration_ms=(perf_counter() - started) * 1000,
            message="maximum steps exceeded",
            metadata={"usage": usage},
        )

    async def _execute_browser_action(self, task: Task, step: int, action: Action) -> ActionResult:
        if self._browser_executor is None:
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=0,
                error="no browser executor is available",
            )
        try:
            result: ActionResult = await self._browser_executor.execute(action)
            return result
        except ActionExecutionError as error:
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=0,
                error=str(error),
            )

    async def _failed(
        self,
        task: Task,
        steps: int,
        started: float,
        message: str,
        final_action: Action | None = None,
        usage: dict[str, int] | None = None,
    ) -> RuntimeResult:
        await self._events.emit("task.failed", task_id=task.id, reason=message)
        return RuntimeResult(
            task_id=task.id,
            status=RuntimeStatus.FAILED,
            steps=steps,
            duration_ms=(perf_counter() - started) * 1000,
            message=message,
            final_action=final_action,
            metadata={"usage": usage or {"input_tokens": 0, "output_tokens": 0}},
        )
