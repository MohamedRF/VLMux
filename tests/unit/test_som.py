"""Tests for Set-of-Marks perception and mark resolution."""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError
from vlmux.perception.som import (
    MARKS_METADATA_KEY,
    RectangleDetector,
    RectangleElement,
    annotate_observation,
    resolve_mark,
)


def _screen(width: int = 200, height: int = 120) -> ScreenObservation:
    image = Image.new("RGB", (width, height), (240, 240, 240))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return ScreenObservation(
        width=width,
        height=height,
        image=base64.b64encode(buffer.getvalue()).decode("ascii"),
        image_format="png",
    )


def test_rectangle_element_center_and_dict() -> None:
    element = RectangleElement(10, 20, 100, 40, label="OK")
    assert element.center == (60, 40)
    assert element.bounds == (10, 20, 110, 60)
    assert element.to_dict()["center"] == [60, 40]


def test_rectangle_detector_finds_nothing_on_blank_screen() -> None:
    assert RectangleDetector().detect(_screen()) == []


def test_annotate_observation_produces_registry() -> None:
    screen = _screen()
    elements = [
        RectangleElement(10, 10, 60, 30, label="A"),
        RectangleElement(100, 60, 60, 30, label="B"),
    ]
    annotated, metadata = annotate_observation(screen, elements)
    assert annotated.image != screen.image
    registry = metadata[MARKS_METADATA_KEY]
    assert set(registry) == {"1", "2"}
    assert resolve_mark(metadata, 1) == (40, 25)
    assert resolve_mark(metadata, 2) == (130, 75)


def test_resolve_mark_rejects_unknown_mark() -> None:
    metadata = {MARKS_METADATA_KEY: {"1": {"center": [5, 5]}}}
    assert resolve_mark(metadata, 1) == (5, 5)
    try:
        resolve_mark(metadata, 9)
    except ActionValidationError as error:
        assert "does not exist" in str(error)
    else:
        raise AssertionError("expected ActionValidationError")


def test_resolve_mark_requires_marks() -> None:
    try:
        resolve_mark({}, 1)
    except ActionValidationError as error:
        assert "Set-of-Marks" in str(error)
    else:
        raise AssertionError("expected ActionValidationError")
