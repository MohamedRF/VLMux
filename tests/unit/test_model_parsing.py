"""Tests for extracting and normalizing untrusted model responses."""

import pytest

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError, ModelResponseError
from vlmux.models.parsing import (
    extract_json_object,
    normalize_action_coordinates,
    parse_model_action,
)
from vlmux.protocol import ClickAction, FinishAction


@pytest.mark.parametrize(
    "raw",
    [
        '{"type":"finish","message":"done"}',
        '```json\n{"type":"finish","message":"done"}\n```',
        'Proposed action: {"type":"finish","message":"done"}',
        '{"action":{"type":"finish","message":"done"}}',
    ],
)
def test_parser_accepts_supported_json_wrappers(raw: str) -> None:
    assert isinstance(parse_model_action(raw), FinishAction)


@pytest.mark.parametrize("raw", ["", "no json", "[]", "{broken", '{"type":"unknown"}'])
def test_parser_rejects_invalid_or_unstructured_output(raw: str) -> None:
    with pytest.raises(ModelResponseError):
        parse_model_action(raw)


def test_balanced_extraction_handles_braces_inside_strings() -> None:
    payload = extract_json_object('text {"type":"type","text":"value } here"} trailing')

    assert payload["text"] == "value } here"


def test_coordinate_normalization_maps_image_pixels_to_native_desktop() -> None:
    screen = ScreenObservation(
        width=100,
        height=50,
        source_width=200,
        source_height=100,
        origin_x=-200,
        origin_y=10,
        image="aQ==",
    )

    action = normalize_action_coordinates(ClickAction(x=50, y=25), screen)

    assert isinstance(action, ClickAction)
    assert (action.x, action.y) == (-100, 60)


def test_coordinate_normalization_rejects_model_coordinates_outside_image() -> None:
    screen = ScreenObservation(width=10, height=10, image="aQ==")

    with pytest.raises(ActionValidationError):
        normalize_action_coordinates(ClickAction(x=10, y=0), screen)
