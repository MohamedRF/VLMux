"""Provider-neutral prompt construction for ordinary vision models."""

import json
from typing import Any

from vlmux.core import AgentContext, Observation, Task
from vlmux.protocol import action_json_schema


def build_system_prompt() -> str:
    """Return strict instructions plus the authoritative VAP JSON Schema."""
    schema = json.dumps(action_json_schema(), separators=(",", ":"))
    return (
        "You are controlling a computer. Choose exactly ONE next action. "
        "Return only one valid JSON object matching the supplied schema. "
        "Do not include markdown or prose. "
        "Coordinate fields must use pixels in the supplied screenshot: x=0,y=0 is its top-left. "
        "Never invent coordinates outside the image. Use finish only when the task is complete. "
        "Use fail when the task cannot safely continue.\nVAP JSON Schema:\n"
        f"{schema}"
    )


def build_user_content(
    task: Task,
    observation: Observation,
    context: AgentContext,
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible multimodal content with concise history."""
    text = build_user_prompt(task, observation, context)
    screen = observation.screen
    media_type = "image/jpeg" if screen.image_format == "jpeg" else f"image/{screen.image_format}"
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{screen.image}"},
        },
    ]


def build_user_prompt(task: Task, observation: Observation, context: AgentContext) -> str:
    """Build provider-neutral task, screen, and recent-history text."""
    history = [
        {
            "step": step.step,
            "action": step.decision.action.type,
            "success": step.result.success if step.result is not None else None,
            "error": step.result.error if step.result is not None else None,
        }
        for step in context.steps
    ]
    screen = observation.screen
    text = json.dumps(
        {
            "task": task.instruction,
            "screenshot": {"width": screen.width, "height": screen.height},
            "recent_steps": history,
            "important_state": context.important_state,
        },
        separators=(",", ":"),
    )
    return text


def build_anthropic_user_content(
    task: Task,
    observation: Observation,
    context: AgentContext,
) -> list[dict[str, Any]]:
    """Build Anthropic Messages API multimodal content."""
    screen = observation.screen
    media_type = "image/jpeg" if screen.image_format == "jpeg" else f"image/{screen.image_format}"
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": screen.image,
            },
        },
        {"type": "text", "text": build_user_prompt(task, observation, context)},
    ]
