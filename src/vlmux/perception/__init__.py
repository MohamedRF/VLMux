"""Screen perception interfaces and production capture providers."""

from vlmux.perception.base import ScreenCaptureProvider
from vlmux.perception.coordinates import image_to_screen_coordinates, screen_to_image_coordinates
from vlmux.perception.factory import create_screen_capture_provider
from vlmux.perception.models import CaptureOptions, CaptureRegion, RawScreenshot
from vlmux.perception.mss_provider import MSSScreenCaptureProvider
from vlmux.perception.som import (
    ElementDetector,
    RectangleDetector,
    RectangleElement,
    UIElement,
    annotate_observation,
    resolve_mark,
)
from vlmux.perception.ui_tree import (
    RefRegistry,
    UITreeElement,
    UITreeProvider,
    UITreeSnapshot,
    assign_occurrences,
    is_interactive,
)

__all__ = [
    "CaptureOptions",
    "CaptureRegion",
    "ElementDetector",
    "MSSScreenCaptureProvider",
    "RawScreenshot",
    "RectangleDetector",
    "RectangleElement",
    "RefRegistry",
    "ScreenCaptureProvider",
    "UIElement",
    "UITreeElement",
    "UITreeProvider",
    "UITreeSnapshot",
    "annotate_observation",
    "assign_occurrences",
    "create_screen_capture_provider",
    "image_to_screen_coordinates",
    "is_interactive",
    "resolve_mark",
    "screen_to_image_coordinates",
]
