"""Validation that requires observation context rather than action syntax."""

from vlmux.core.models import ScreenObservation
from vlmux.exceptions import ActionValidationError
from vlmux.protocol.actions import Action, CoordinateAction, DragAction, ScrollAction


def validate_action_coordinates(action: Action, screen: ScreenObservation) -> None:
    """Ensure all coordinates in an action lie within the source screen bounds.

    Actions use native screen pixels. When an image is resized, source dimensions
    are therefore used instead of the encoded image dimensions.
    """
    width = screen.source_width or screen.width
    height = screen.source_height or screen.height

    coordinates: list[tuple[str, int, int]] = []
    if isinstance(action, CoordinateAction):
        coordinates.append(("target", action.x, action.y))
    elif isinstance(action, DragAction):
        coordinates.extend(
            [
                ("start", action.start_x, action.start_y),
                ("end", action.end_x, action.end_y),
            ]
        )
    elif isinstance(action, ScrollAction) and action.x is not None and action.y is not None:
        coordinates.append(("target", action.x, action.y))

    for label, x, y in coordinates:
        if not (
            screen.origin_x <= x < screen.origin_x + width
            and screen.origin_y <= y < screen.origin_y + height
        ):
            raise ActionValidationError(
                f"{label} coordinate ({x}, {y}) is outside the captured screen region"
            )
