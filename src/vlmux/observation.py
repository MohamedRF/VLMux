"""Composition of low-level perception into runtime observations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from vlmux.core import Observation, PerceptionMode
from vlmux.perception import (
    CaptureOptions,
    ElementDetector,
    ScreenCaptureProvider,
    annotate_observation,
)


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


class SetOfMarksObserver(Observer):
    """Wrap another observer, annotating screenshots with numbered marks."""

    def __init__(self, inner: Observer, detector: ElementDetector) -> None:
        self._inner = inner
        self._detector = detector

    async def capture(self) -> Observation:
        """Capture and annotate one observation with Set-of-Marks labels."""
        observation = await self._inner.capture()
        elements = self._detector.detect(observation.screen)
        if not elements:
            return observation
        annotated_screen, metadata = annotate_observation(observation.screen, elements)
        return observation.model_copy(
            update={
                "screen": annotated_screen,
                "mode": PerceptionMode.SET_OF_MARKS,
                "metadata": {**observation.metadata, **metadata},
            }
        )


class HybridObserver(Observer):
    """Combine SoM annotation with DOM metadata when a browser is attached."""

    def __init__(self, inner: Observer, detector: ElementDetector | None = None) -> None:
        self._inner = inner
        self._detector = detector

    async def capture(self) -> Observation:
        """Capture, annotate marks, and preserve any DOM metadata."""
        observation = await self._inner.capture()
        if self._detector is None:
            return observation.model_copy(update={"mode": PerceptionMode.HYBRID})
        elements = self._detector.detect(observation.screen)
        if not elements:
            return observation.model_copy(update={"mode": PerceptionMode.HYBRID})
        annotated_screen, metadata = annotate_observation(observation.screen, elements)
        return observation.model_copy(
            update={
                "screen": annotated_screen,
                "mode": PerceptionMode.HYBRID,
                "metadata": {**observation.metadata, **metadata},
            }
        )
