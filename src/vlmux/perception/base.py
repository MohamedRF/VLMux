"""Abstract screen-capture boundary."""

from abc import ABC, abstractmethod

from vlmux.core import ScreenObservation
from vlmux.perception.models import CaptureOptions


class ScreenCaptureProvider(ABC):
    """Capture encoded screen images without exposing a platform library."""

    @abstractmethod
    async def capture(self, options: CaptureOptions | None = None) -> ScreenObservation:
        """Capture a screen region and return transport-ready image data."""
