"""Composition of low-level perception into runtime observations."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from vlmux.core import Observation, PerceptionMode, WindowInfo
from vlmux.exceptions import ScreenCaptureError
from vlmux.perception import (
    CaptureOptions,
    ElementDetector,
    ScreenCaptureProvider,
    UITreeProvider,
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


class UITreeObserver(Observer):
    """Wrap an observer, attaching a ref-tagged accessibility tree.

    The model receives screenshot plus compact ref lines (in ``metadata``);
    actions such as ``click_ref``/``set_value_ref`` target those refs, and the
    shared registry re-locates the live element at action time.
    """

    def __init__(
        self,
        inner: Observer,
        provider: UITreeProvider,
        *,
        app: str | None = None,
        window_id: str | None = None,
        interactive_only: bool = True,
        max_elements: int = 500,
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._app = app
        self._window_id = window_id
        self._interactive_only = interactive_only
        self._max_elements = max_elements

    async def capture(self) -> Observation:
        """Capture screen plus the accessibility tree, or raise cleanly."""

        observation = await self._inner.capture()
        try:
            snapshot = await asyncio.to_thread(
                self._provider.snapshot,
                window_id=self._window_id,
                app=self._app,
                interactive_only=self._interactive_only,
                max_elements=self._max_elements,
            )
        except ScreenCaptureError:
            raise
        except Exception as error:
            raise ScreenCaptureError(f"accessibility snapshot failed: {error}") from error
        tree = snapshot.to_dict()
        return observation.model_copy(
            update={
                "mode": PerceptionMode.UI_TREE,
                "accessibility": tree,
                "metadata": {
                    **observation.metadata,
                    "ui_snapshot_id": snapshot.snapshot_id,
                    "ui_ref_count": len(snapshot.refs),
                    "ui_complete": snapshot.complete,
                    "ui_tree": snapshot.render_lines(),
                },
            }
        )


class OCRObserver(Observer):
    """Wrap another observer, attaching recognized text to the observation."""

    def __init__(self, inner: Observer, ocr: OCRProvider) -> None:
        self._inner = inner
        self._ocr = ocr

    async def capture(self) -> Observation:
        """Capture and attach recognition results; failures become capture errors."""
        observation = await self._inner.capture()
        try:
            words = self._ocr.recognize(observation.screen)
        except Exception as error:
            raise ScreenCaptureError(f"OCR recognition failed: {error}") from error
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
        try:
            tree = self._provider.tree()
        except Exception as error:
            raise ScreenCaptureError(f"accessibility tree capture failed: {error}") from error
        windows: list[WindowInfo] = []
        for child in tree.get("children", []):
            if child.get("window_id") is None:
                continue
            bounds = child.get("bounds") or {}
            windows.append(
                WindowInfo(
                    id=str(child["window_id"]),
                    title=str(child.get("name", "")),
                    focused=bool(child.get("focused", False)),
                    x=bounds.get("x"),
                    y=bounds.get("y"),
                    width=bounds.get("width"),
                    height=bounds.get("height"),
                )
            )
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
        try:
            elements = self._detector.detect(observation.screen)
        except Exception as error:
            raise ScreenCaptureError(f"element detection failed: {error}") from error
        if not elements:
            return observation
        try:
            annotated_screen, metadata = annotate_observation(observation.screen, elements)
        except Exception as error:
            raise ScreenCaptureError(f"Set-of-Marks annotation failed: {error}") from error
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
            try:
                words = self._ocr.recognize(observation.screen)
            except Exception as error:
                raise ScreenCaptureError(f"OCR recognition failed: {error}") from error
            ocr_entries, text = ocr_payload(words)
            metadata["ocr_text"] = text
        screen = observation.screen
        if self._detector is not None:
            try:
                elements = self._detector.detect(screen)
            except Exception as error:
                raise ScreenCaptureError(f"element detection failed: {error}") from error
            if elements:
                try:
                    screen, mark_metadata = annotate_observation(screen, elements)
                except Exception as error:
                    raise ScreenCaptureError(f"Set-of-Marks annotation failed: {error}") from error
                metadata.update(mark_metadata)
        return observation.model_copy(
            update={
                "mode": PerceptionMode.HYBRID,
                "screen": screen,
                "ocr": ocr_entries,
                "metadata": metadata,
            }
        )
