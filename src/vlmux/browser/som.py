"""DOM-backed Set-of-Marks detection for browser-driven observations."""

from __future__ import annotations

from typing import Any

from vlmux.core import ScreenObservation
from vlmux.perception.som import RectangleElement, UIElement


class DomElementDetector:
    """Convert browser interactive elements into numbered SoM elements.

    Elements arrive in page/viewport coordinates from
    ``BrowserSession.interactive_elements``; they map directly into the page
    screenshot's image space when the screenshot is a viewport capture.
    """

    def __init__(self, elements: list[dict[str, Any]]) -> None:
        self._elements = elements

    def detect(self, screen: ScreenObservation) -> list[UIElement]:
        """Return one markable element per interactive DOM element."""
        elements: list[UIElement] = []
        for entry in self._elements:
            try:
                x = int(entry["x"])
                y = int(entry["y"])
                width = int(entry.get("width", 0))
                height = int(entry.get("height", 0))
            except (KeyError, TypeError, ValueError):
                continue
            if width <= 0 or height <= 0:
                continue
            if not (0 <= x < screen.width and 0 <= y < screen.height):
                continue
            label = str(entry.get("text") or entry.get("selector") or "")
            elements.append(
                RectangleElement(
                    max(0, x - width // 2),
                    max(0, y - height // 2),
                    width,
                    height,
                    label=label,
                    source="dom",
                )
            )
        return elements
