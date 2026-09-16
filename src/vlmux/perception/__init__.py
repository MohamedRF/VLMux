"""Screen perception interfaces and production capture providers."""

from vlmux.perception.base import ScreenCaptureProvider
from vlmux.perception.coordinates import image_to_screen_coordinates, screen_to_image_coordinates
from vlmux.perception.factory import create_screen_capture_provider
from vlmux.perception.models import CaptureOptions, CaptureRegion, RawScreenshot
from vlmux.perception.mss_provider import MSSScreenCaptureProvider

__all__ = [
    "CaptureOptions",
    "CaptureRegion",
    "MSSScreenCaptureProvider",
    "RawScreenshot",
    "ScreenCaptureProvider",
    "create_screen_capture_provider",
    "image_to_screen_coordinates",
    "screen_to_image_coordinates",
]
