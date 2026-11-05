"""Tests for OCR, accessibility, and DOM SoM perception."""

from __future__ import annotations

import asyncio
from typing import Any

from vlmux.browser.som import DomElementDetector
from vlmux.core import Observation, PerceptionMode, ScreenObservation
from vlmux.observation import A11yObserver, OCRObserver
from vlmux.perception.ocr import OCRWord, StubOCRProvider, ocr_payload


class FakeInner:
    async def capture(self) -> Observation:
        return Observation(screen=ScreenObservation(width=100, height=80, image="aQ=="))


def test_stub_ocr_payload() -> None:
    provider = StubOCRProvider([OCRWord("Hello", 1, 2, 30, 10)])
    screen = ScreenObservation(width=100, height=80, image="aQ==")
    words = provider.recognize(screen)
    entries, text = ocr_payload(words)
    assert text == "Hello"
    assert entries[0]["text"] == "Hello"


def test_ocr_observer_attaches_text() -> None:
    provider = StubOCRProvider([OCRWord("81263", 5, 6, 40, 12)])
    observer = OCRObserver(FakeInner(), provider)  # type: ignore[arg-type]
    observation = asyncio.run(observer.capture())
    assert observation.mode is PerceptionMode.OCR
    assert observation.metadata["ocr_text"] == "81263"
    assert observation.ocr[0]["text"] == "81263"


def test_a11y_observer_attaches_windows() -> None:
    class FakeA11y:
        def tree(self) -> dict[str, Any]:
            return {
                "role": "application",
                "children": [
                    {
                        "role": "window",
                        "name": "Calculator",
                        "window_id": "42",
                        "focused": True,
                        "bounds": {"x": 0, "y": 0, "width": 300, "height": 200},
                    }
                ],
            }

    observer = A11yObserver(FakeInner(), FakeA11y())  # type: ignore[arg-type]
    observation = asyncio.run(observer.capture())
    assert observation.mode is PerceptionMode.A11Y
    assert observation.windows[0].title == "Calculator"
    assert observation.accessibility is not None


def test_dom_element_detector_filters_invalid_entries() -> None:
    screen = ScreenObservation(width=400, height=300, image="aQ==")
    detector = DomElementDetector(
        [
            {"x": 50, "y": 60, "width": 40, "height": 20, "text": "Go", "selector": "#go"},
            {"x": 999, "y": 999, "width": 40, "height": 20},
            {"x": 10, "y": 10, "width": 0, "height": 0},
            {"garbage": True},
        ]
    )
    elements = detector.detect(screen)
    assert len(elements) == 1
    assert elements[0].label == "Go"
    assert elements[0].center == (50, 60)
