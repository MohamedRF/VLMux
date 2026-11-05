"""Set-of-Marks perception: annotate interactive elements with numbered labels.

The model returns ``{"type": "click_mark", "mark": N}`` and the runtime
resolves ``N`` to screen coordinates through :func:`resolve_mark`. Detectors
are pluggable so DOM, accessibility, and future object-detection providers
can supply elements without touching the runtime.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Protocol

from PIL import Image, ImageDraw, ImageFont

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError

#: Observation metadata key under which the mark registry is stored.
MARKS_METADATA_KEY = "set_of_marks"


class UIElement(Protocol):
    """One clickable element in encoded-image pixel coordinates."""

    @property
    def label(self) -> str: ...

    @property
    def center(self) -> tuple[int, int]: ...

    @property
    def bounds(self) -> tuple[int, int, int, int]: ...


class ElementDetector(Protocol):
    """Supply candidate interactive elements for an observation."""

    def detect(self, screen: ScreenObservation) -> list[UIElement]:
        """Return candidate elements in encoded-image pixel coordinates."""
        ...


class RectangleElement:
    """A UIElement backed by an axis-aligned image-space rectangle."""

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        label: str = "",
        source: str = "detector",
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("element dimensions must be positive")
        self.x = max(0, x)
        self.y = max(0, y)
        self.width = width
        self.height = height
        self.label = label
        self.source = source

    @property
    def center(self) -> tuple[int, int]:
        """Return the element center in encoded-image pixels."""
        return self.x + self.width // 2, self.y + self.height // 2

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Return ``(x, y, x + width, y + height)``."""
        return self.x, self.y, self.x + self.width, self.y + self.height

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable description of this element."""
        return {
            "label": self.label,
            "source": self.source,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "center": list(self.center),
        }


def _rectangles_overlap(a: RectangleElement, b: RectangleElement) -> bool:
    """Return True when two rectangles share more than half of the smaller."""
    ax1, ay1, ax2, ay2 = a.bounds
    bx1, by1, bx2, by2 = b.bounds
    overlap_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    overlap_h = max(0, min(ay2, by2) - max(ay1, by1))
    smaller = min(a.width * a.height, b.width * b.height)
    return smaller > 0 and (overlap_w * overlap_h) / smaller > 0.5


class RectangleDetector:
    """Detect rectangular UI regions with a lightweight edge-difference scan.
    This is intentionally dependency-free (Pillow only). It finds
    horizontally bounded runs whose interior differs from the background up
    to a bounded height. It is a usable default, not a replacement for DOM
    or accessibility-tree elements where those are available.
    """

    def __init__(
        self,
        *,
        min_width: int = 40,
        min_height: int = 16,
        contrast_threshold: int = 24,
        scan_step: int = 4,
        max_elements: int = 64,
    ) -> None:
        self._min_width = min_width
        self._min_height = min_height
        self._threshold = contrast_threshold
        self._step = max(1, scan_step)
        self._max = max_elements

    def detect(self, screen: ScreenObservation) -> list[UIElement]:
        """Scan the screenshot for rectangle candidates."""
        image = Image.open(BytesIO(base64.b64decode(screen.image))).convert("L")
        width, height = image.size
        pixels = image.load()
        if pixels is None:
            return []
        step = self._step
        candidates: list[RectangleElement] = []
        for y in range(0, height, step):
            in_run = False
            run_start = 0
            for x in range(0, width, step):
                edge = self._edge(pixels, x, y, width, height)
                if edge >= self._threshold and not in_run:
                    in_run = True
                    run_start = x
                elif edge < self._threshold and in_run:
                    in_run = False
                    self._maybe_add(candidates, pixels, run_start, y, x - run_start, width, height)
            if in_run:
                self._maybe_add(candidates, pixels, run_start, y, width - run_start, width, height)
        merged: list[RectangleElement] = []
        for candidate in sorted(candidates, key=lambda c: c.width * c.height, reverse=True):
            if any(_rectangles_overlap(candidate, other) for other in merged):
                continue
            merged.append(candidate)
            if len(merged) >= self._max:
                break
        merged.sort(key=lambda c: (c.y, c.x))
        return list(merged)

    def _edge(self, pixels: Any, x: int, y: int, width: int, height: int) -> int:
        x2 = min(x + 2, width - 1)
        y2 = min(y + 2, height - 1)
        return abs(int(pixels[x, y]) - int(pixels[x2, y2]))

    def _maybe_add(
        self,
        out: list[RectangleElement],
        pixels: Any,
        x: int,
        y: int,
        run_width: int,
        width: int,
        height: int,
    ) -> None:
        if run_width < self._min_width:
            return
        probe_x = min(x + run_width // 2, width - 1)
        base = int(pixels[probe_x, y])
        max_height = min(120, height - y)
        element_height = self._min_height
        for dy in range(2, max_height, 2):
            if abs(int(pixels[probe_x, y + dy]) - base) >= self._threshold:
                element_height = dy
                break
        else:
            element_height = max_height
        if element_height >= self._min_height:
            out.append(RectangleElement(x, y, run_width, element_height))


def annotate_observation(
    screen: ScreenObservation,
    elements: list[UIElement],
) -> tuple[ScreenObservation, dict[str, Any]]:
    """Draw numbered badges and return the annotated screen plus registry."""
    image = Image.open(BytesIO(base64.b64decode(screen.image))).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for index, element in enumerate(elements, start=1):
        x, y, _, _ = element.bounds
        label = str(index)
        text_box = draw.textbbox((0, 0), label, font=font)
        box_w = text_box[2] - text_box[0] + 8
        box_h = text_box[3] - text_box[1] + 6
        badge_x = max(0, x)
        badge_y = max(0, y - box_h - 2)
        draw.rectangle([badge_x, badge_y, badge_x + box_w, badge_y + box_h], fill=(220, 38, 38))
        draw.text((badge_x + 4, badge_y + 3), label, fill=(255, 255, 255), font=font)
        cx, cy = element.center
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(220, 38, 38))
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    annotated = screen.model_copy(
        update={
            "image": base64.b64encode(encoded.getvalue()).decode("ascii"),
            "image_format": "png",
            "width": image.width,
            "height": image.height,
        }
    )
    registry: dict[str, Any] = {}
    for index, element in enumerate(elements, start=1):
        if isinstance(element, RectangleElement):
            registry[str(index)] = element.to_dict()
        else:
            registry[str(index)] = {"center": list(element.center), "label": element.label}
    return annotated, {MARKS_METADATA_KEY: registry}


def resolve_mark(metadata: dict[str, Any], mark: int) -> tuple[int, int]:
    """Resolve a mark number to encoded-image pixels from observation metadata."""
    registry = metadata.get(MARKS_METADATA_KEY)
    if not isinstance(registry, dict):
        raise ActionValidationError(
            "click_mark requires Set-of-Marks perception; current observation has no marks"
        )
    entry = registry.get(str(mark))
    if not isinstance(entry, dict) or "center" not in entry:
        raise ActionValidationError(f"mark {mark} does not exist in the current observation")
    center = entry["center"]
    if not (isinstance(center, list) and len(center) == 2):
        raise ActionValidationError(f"mark {mark} has invalid coordinates")
    return int(center[0]), int(center[1])
