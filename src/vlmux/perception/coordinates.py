"""Coordinate transforms between encoded images and native screen pixels."""

import math

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError


def image_to_screen_coordinates(x: int, y: int, screen: ScreenObservation) -> tuple[int, int]:
    """Map an encoded-image pixel to its absolute source-screen coordinate."""
    if x < 0 or y < 0 or x >= screen.width or y >= screen.height:
        raise ActionValidationError(
            f"image coordinate ({x}, {y}) is outside the {screen.width}x{screen.height} image"
        )
    source_width = screen.source_width or screen.width
    source_height = screen.source_height or screen.height
    source_x = math.floor(x * source_width / screen.width)
    source_y = math.floor(y * source_height / screen.height)
    return screen.origin_x + source_x, screen.origin_y + source_y


def screen_to_image_coordinates(x: int, y: int, screen: ScreenObservation) -> tuple[int, int]:
    """Map an absolute source-screen coordinate to the encoded image."""
    source_width = screen.source_width or screen.width
    source_height = screen.source_height or screen.height
    relative_x = x - screen.origin_x
    relative_y = y - screen.origin_y
    if (
        relative_x < 0
        or relative_y < 0
        or relative_x >= source_width
        or relative_y >= source_height
    ):
        raise ActionValidationError(
            f"screen coordinate ({x}, {y}) is outside the captured screen region"
        )
    image_x = min(math.floor(relative_x * screen.width / source_width), screen.width - 1)
    image_y = min(math.floor(relative_y * screen.height / source_height), screen.height - 1)
    return image_x, image_y
