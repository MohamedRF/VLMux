"""Composition of low-level perception into runtime observations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from vlmux.core import Observation, PerceptionMode, WindowInfo
from vlmux.perception import (
    CaptureOptions,
    ElementDetector,
    ScreenCaptureProvider,
    annotate_observation,
)
from vlmux.perception.a11y import AccessibilityProvider
from vlmux.perception.ocr import OCRProvider, ocr_payload


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


class OCRObserver(Observer):
    """Wrap another observer, attaching recognized text to the observation."""

    def __init__(self, inner: Observer, ocr: OCRProvider) -> None:
        self._inner = inner
        self._ocr = ocr

    async def capture(self) -> Observation:
        """Capture and attach OCR words plus joined text for verifiers."""
        observation = await self._inner.capture()
        words = self._ocr.recognize(observation.screen)
        entries, text = ocr_payload(words)
        return observation.model_copy(
            update={
                "mode": PerceptionMode.OCR,
                "ocr": entries,
                "metadata": {**observation.metadata, "ocr_text": text},
            }
        )


class A11yObserver(Observer):
    """Wrap another observer, attaching the accessibility tree and windows."""

    def __init__(self, inner: Observer, provider: AccessibilityProvider) -> None:
        self._inner = inner
        self._provider = provider

    async def capture(self) -> Observation:
        """Capture and attach window metadata plus the accessibility tree."""
        observation = await self._inner.capture()
        tree = self._provider.tree()
        windows = [
            WindowInfo(
                id=str(child.get("window_id")),
                title=str(child.get("name", "")),
                focused=bool(child.get("focused", False)),
                x=(child.get("bounds") or {}).get("x"),
                y=(child.get("bounds") or {}).get("y"),
                width=(child.get("bounds") or {}).get("width"),
                height=(child.get("bounds") or {}).get("height"),
            )
            for child in tree.get("children", [])
        ]
        return observation.model_copy(
            update={
                "mode": PerceptionMode.A11Y,
                "accessibility": tree,
                "windows": windows or observation.windows,
            }
        )


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
    """Combine SoM annotation, OCR text, and DOM metadata when available."""

    def __init__(
        self,
        inner: Observer,
        detector: ElementDetector | None = None,
        ocr: OCRProvider | None = None,
    ) -> None:
        self._inner = inner
        self._detector = detector
        self._ocr = ocr

    async def capture(self) -> Observation:
        """Capture, annotate marks, attach OCR, preserve DOM metadata."""
        observation = await self._inner.capture()
        metadata = dict(observation.metadata)
        ocr_entries: list[dict[str, Any]] = observation.ocr
        if self._ocr is not None:
            words = self._ocr.recognize(observation.screen)
            ocr_entries, text = ocr_payload(words)
            metadata["ocr_text"] = text
        screen = observation.screen
        if self._detector is not None:
            elements = self._detector.detect(screen)
            if elements:
                screen, mark_metadata = annotate_observation(screen, elements)
                metadata.update(mark_metadata)
        return observation.model_copy(
            update={
                "mode": PerceptionMode.HYBRID,
                "screen": screen,
                "ocr": ocr_entries,
                "metadata": metadata,
            }
        )
