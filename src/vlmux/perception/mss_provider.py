"""MSS/Pillow screen capture implementation."""

from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from typing import Any, Protocol

from PIL import Image

from vlmux.core import ScreenObservation
from vlmux.exceptions import ScreenCaptureError, UnsupportedPlatformError
from vlmux.perception.base import ScreenCaptureProvider
from vlmux.perception.models import CaptureOptions, CaptureRegion, RawScreenshot


class ScreenshotBackend(Protocol):
    """Synchronous raw-pixel boundary used by the async provider."""

    def monitor_regions(self) -> list[CaptureRegion]:
        """Return virtual-screen and physical-monitor rectangles."""

    def grab(self, region: CaptureRegion) -> RawScreenshot:
        """Capture one region as packed RGB bytes."""


class ActiveWindowRegionProvider(Protocol):
    """Return the active native window rectangle when supported."""

    def active_window_region(self) -> CaptureRegion:
        """Resolve the foreground window bounds."""


class MSSBackend:
    """Thin synchronous adapter around the optional native MSS API."""

    def monitor_regions(self) -> list[CaptureRegion]:
        try:
            import mss

            with mss.mss() as capture:
                return [
                    CaptureRegion(
                        left=int(monitor["left"]),
                        top=int(monitor["top"]),
                        width=int(monitor["width"]),
                        height=int(monitor["height"]),
                        monitor=index,
                    )
                    for index, monitor in enumerate(capture.monitors)
                ]
        except Exception as error:
            raise ScreenCaptureError("unable to enumerate displays") from error

    def grab(self, region: CaptureRegion) -> RawScreenshot:
        try:
            import mss

            monitor = {
                "left": region.left,
                "top": region.top,
                "width": region.width,
                "height": region.height,
            }
            with mss.mss() as capture:
                screenshot = capture.grab(monitor)
                return RawScreenshot(region=region, rgb=screenshot.rgb)
        except ScreenCaptureError:
            raise
        except Exception as error:
            raise ScreenCaptureError("unable to capture the requested screen region") from error


class MSSScreenCaptureProvider(ScreenCaptureProvider):
    """Capture, resize, and encode screenshots without blocking the event loop."""

    def __init__(
        self,
        *,
        backend: ScreenshotBackend | None = None,
        active_window_provider: ActiveWindowRegionProvider | None = None,
    ) -> None:
        self._backend = backend or MSSBackend()
        self._active_window_provider = active_window_provider

    async def capture(self, options: CaptureOptions | None = None) -> ScreenObservation:
        """Capture a monitor or active window in a worker thread."""
        capture_options = options or CaptureOptions()
        return await asyncio.to_thread(self._capture_sync, capture_options)

    def _capture_sync(self, options: CaptureOptions) -> ScreenObservation:
        try:
            region = self._resolve_region(options)
            screenshot = self._backend.grab(region)
            return self._encode(screenshot, options)
        except (ScreenCaptureError, UnsupportedPlatformError):
            raise
        except Exception as error:
            raise ScreenCaptureError("screen capture processing failed") from error

    def _resolve_region(self, options: CaptureOptions) -> CaptureRegion:
        if options.active_window:
            if self._active_window_provider is None:
                raise UnsupportedPlatformError(
                    "active-window capture is unavailable on this platform"
                )
            return self._active_window_provider.active_window_region()

        regions = self._backend.monitor_regions()
        if not regions:
            raise ScreenCaptureError("no displays were reported by the capture backend")
        monitor = 0 if options.monitor is None else options.monitor
        if monitor >= len(regions):
            available = max(len(regions) - 1, 0)
            raise ScreenCaptureError(
                f"monitor {monitor} is unavailable; valid monitor indices are 0 through {available}"
            )
        return regions[monitor]

    @staticmethod
    def _encode(screenshot: RawScreenshot, options: CaptureOptions) -> ScreenObservation:
        image = Image.frombytes(
            "RGB",
            (screenshot.region.width, screenshot.region.height),
            screenshot.rgb,
        )
        original_width, original_height = image.size
        if options.max_width is not None or options.max_height is not None:
            maximum_size = (
                options.max_width or original_width,
                options.max_height or original_height,
            )
            image.thumbnail(maximum_size, Image.Resampling.LANCZOS)

        encoded = BytesIO()
        save_options: dict[str, Any] = {}
        if options.image_format == "jpeg":
            save_options.update(quality=options.quality, optimize=True)
        image.save(encoded, format=options.image_format.upper(), **save_options)

        resized = image.size != (original_width, original_height)
        return ScreenObservation(
            width=image.width,
            height=image.height,
            image=base64.b64encode(encoded.getvalue()).decode("ascii"),
            image_format=options.image_format,
            source_width=original_width if resized else None,
            source_height=original_height if resized else None,
            origin_x=screenshot.region.left,
            origin_y=screenshot.region.top,
            monitor=screenshot.region.monitor,
        )
