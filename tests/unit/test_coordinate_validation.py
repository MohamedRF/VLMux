"""Tests for screen-dependent coordinate checks."""

import pytest
from pydantic import ValidationError

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError
from vlmux.protocol import ClickAction, DragAction, ScrollAction, TypeAction
from vlmux.protocol.validation import validate_action_coordinates


def screen(*, width: int = 100, height: int = 50) -> ScreenObservation:
    return ScreenObservation(width=width, height=height, image="aQ==")


def test_accepts_coordinate_inside_screen() -> None:
    validate_action_coordinates(ClickAction(x=99, y=49), screen())


def test_rejects_coordinate_on_or_beyond_screen_edge() -> None:
    with pytest.raises(ActionValidationError, match="outside"):
        validate_action_coordinates(ClickAction(x=100, y=49), screen())

    with pytest.raises(ActionValidationError, match="outside"):
        validate_action_coordinates(ClickAction(x=-1, y=0), screen())


def test_checks_both_drag_coordinates() -> None:
    with pytest.raises(ActionValidationError, match="end coordinate"):
        validate_action_coordinates(
            DragAction(start_x=0, start_y=0, end_x=100, end_y=10),
            screen(),
        )


def test_uses_native_dimensions_for_resized_screenshot() -> None:
    resized = ScreenObservation(
        width=100,
        height=50,
        source_width=200,
        source_height=100,
        image="aQ==",
    )
    validate_action_coordinates(ClickAction(x=199, y=99), resized)


def test_validates_against_absolute_capture_origin() -> None:
    region = ScreenObservation(
        width=100,
        height=50,
        image="aQ==",
        origin_x=100,
        origin_y=200,
    )

    validate_action_coordinates(ClickAction(x=199, y=249), region)
    with pytest.raises(ActionValidationError, match="outside"):
        validate_action_coordinates(ClickAction(x=99, y=200), region)


def test_accepts_negative_coordinates_in_negative_origin_region() -> None:
    region = ScreenObservation(
        width=100,
        height=50,
        image="aQ==",
        origin_x=-100,
        origin_y=-50,
    )

    validate_action_coordinates(ClickAction(x=-1, y=-1), region)


def test_scroll_position_requires_complete_coordinate_pair() -> None:
    with pytest.raises(ValidationError, match="supplied together"):
        ScrollAction(delta_y=1, x=5)


def test_non_coordinate_action_needs_no_screen_check() -> None:
    validate_action_coordinates(TypeAction(text="hello"), screen())
