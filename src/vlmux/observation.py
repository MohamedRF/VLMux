"""Composition of low-level perception into runtime observations."""

from abc import ABC, abstractmethod

from vlmux.core import Observation
from vlmux.perception import CaptureOptions, ScreenCaptureProvider


class Observer(ABC):
    """Produce one provider-independent observation for a runtime step."""

    @abstractmethod
    async def capture(self) -> Observation:
        """Capture the current observable state."""


class ScreenObserver(Observer):
    """Wrap a screen provider as the initial RAW observation source."""

    def __init__(self, provider: ScreenCaptureProvider, options: CaptureOptions) -> None:
        self._provider = provider
        self._options = options

    async def capture(self) -> Observation:
        return Observation(screen=await self._provider.capture(self._options))
