"""Strict extraction and normalization of untrusted model output."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from vlmux.core import ScreenObservation
from vlmux.exceptions import ModelResponseError
from vlmux.perception import image_to_screen_coordinates
from vlmux.protocol import Action
from vlmux.protocol.actions import ACTION_ADAPTER, CoordinateAction, DragAction, ScrollAction


def extract_json_object(raw_response: str) -> dict[str, Any]:
    """Extract one JSON object without accepting arbitrary prose as an action."""
    response = raw_response.strip()
    if not response:
        raise ModelResponseError("model returned an empty response")

    direct = _load_object(response)
    if direct is not None:
        return direct

    if response.startswith("```") and response.endswith("```"):
        lines = response.splitlines()
        if len(lines) >= 3:
            fenced = "\n".join(lines[1:-1]).strip()
            direct = _load_object(fenced)
            if direct is not None:
                return direct

    candidate = _first_balanced_object(response)
    if candidate is not None:
        parsed = _load_object(candidate)
        if parsed is not None:
            return parsed
    raise ModelResponseError("model response did not contain one valid JSON object")


def parse_model_action(raw_response: str) -> Action:
    """Extract and validate one action, accepting an optional action envelope."""
    payload = extract_json_object(raw_response)
    candidate: object = payload.get("action", payload)
    try:
        return ACTION_ADAPTER.validate_python(candidate)
    except ValidationError as error:
        raise ModelResponseError("model response did not match the VAP action schema") from error


def normalize_action_coordinates(action: Action, screen: ScreenObservation) -> Action:
    """Convert model image-pixel coordinates into absolute source-screen pixels."""
    updates: dict[str, object] = {}
    if isinstance(action, CoordinateAction):
        updates["x"], updates["y"] = image_to_screen_coordinates(action.x, action.y, screen)
    elif isinstance(action, DragAction):
        updates["start_x"], updates["start_y"] = image_to_screen_coordinates(
            action.start_x,
            action.start_y,
            screen,
        )
        updates["end_x"], updates["end_y"] = image_to_screen_coordinates(
            action.end_x,
            action.end_y,
            screen,
        )
    elif isinstance(action, ScrollAction) and action.x is not None and action.y is not None:
        updates["x"], updates["y"] = image_to_screen_coordinates(action.x, action.y, screen)
    if not updates:
        return action
    return ACTION_ADAPTER.validate_python(action.model_copy(update=updates))


def _load_object(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_balanced_object(value: str) -> str | None:
    start = value.find("{")
    if start < 0:
        return None
    depth = 0
    inside_string = False
    escaped = False
    for index, character in enumerate(value[start:], start=start):
        if inside_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                inside_string = False
            continue
        if character == '"':
            inside_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return None
