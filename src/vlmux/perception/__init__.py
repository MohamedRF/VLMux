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

__all__ = [
    "CaptureOptions",
    "CaptureRegion",
    "ElementDetector",
    "MSSScreenCaptureProvider",
    "RawScreenshot",
    "RectangleDetector",
    "RectangleElement",
    "ScreenCaptureProvider",
    "UIElement",
    "annotate_observation",
    "create_screen_capture_provider",
    "image_to_screen_coordinates",
    "resolve_mark",
    "screen_to_image_coordinates",
]
