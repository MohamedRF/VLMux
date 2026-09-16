"""Tests for screen capture, encoding, and coordinate transforms."""

import asyncio
import base64
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from vlmux.core import ScreenObservation
from vlmux.exceptions import ActionValidationError, ScreenCaptureError, UnsupportedPlatformError
from vlmux.perception import (
    CaptureOptions,
    CaptureRegion,
    MSSScreenCaptureProvider,
    RawScreenshot,
    image_to_screen_coordinates,
    screen_to_image_coordinates,
)


class FakeScreenshotBackend:
    def __init__(self, regions: list[CaptureRegion]) -> None:
        self.regions = regions
        self.captured_region: CaptureRegion | None = None
        self.error: Exception | None = None

    def monitor_regions(self) -> list[CaptureRegion]:
        return self.regions

    def grab(self, region: CaptureRegion) -> RawScreenshot:
        if self.error is not None:
            raise self.error
        self.captured_region = region
        return RawScreenshot(region=region, rgb=b"\xff\x00\x00" * region.width * region.height)


class FakeActiveWindowProvider:
    def __init__(self, region: CaptureRegion) -> None:
        self.region = region

    def active_window_region(self) -> CaptureRegion:
        return self.region


def capture(
    provider: MSSScreenCaptureProvider,
    options: CaptureOptions | None = None,
) -> ScreenObservation:
    return asyncio.run(provider.capture(options))


def test_capture_options_reject_conflicting_targets() -> None:
    with pytest.raises(ValidationError, match="cannot be used together"):
        CaptureOptions(monitor=1, active_window=True)


def test_raw_screenshot_validates_rgb_buffer_length() -> None:
    with pytest.raises(ValueError, match="does not match"):
        RawScreenshot(region=CaptureRegion(0, 0, 2, 2), rgb=b"too short")


def test_capture_resizes_encodes_and_preserves_source_mapping() -> None:
    backend = FakeScreenshotBackend([CaptureRegion(10, 20, 200, 100, monitor=0)])
    provider = MSSScreenCaptureProvider(backend=backend)

    observation = capture(
        provider,
        CaptureOptions(max_width=100, max_height=100, image_format="png"),
    )

    assert (observation.width, observation.height) == (100, 50)
    assert (observation.source_width, observation.source_height) == (200, 100)
    assert (observation.origin_x, observation.origin_y) == (10, 20)
    assert observation.monitor == 0
    image = Image.open(BytesIO(base64.b64decode(observation.image)))
    assert image.size == (100, 50)
    assert image.format == "PNG"


def test_capture_without_resize_omits_redundant_source_dimensions() -> None:
    backend = FakeScreenshotBackend([CaptureRegion(0, 0, 2, 1, monitor=0)])
    provider = MSSScreenCaptureProvider(backend=backend)

    observation = capture(
        provider,
        CaptureOptions(max_width=None, max_height=None, image_format="jpeg", quality=70),
    )

    assert observation.source_width is None
    assert observation.source_height is None
    assert Image.open(BytesIO(base64.b64decode(observation.image))).format == "JPEG"


def test_capture_selects_requested_monitor() -> None:
    regions = [
        CaptureRegion(0, 0, 4, 2, monitor=0),
        CaptureRegion(4, 0, 2, 2, monitor=1),
    ]
    backend = FakeScreenshotBackend(regions)

    capture(MSSScreenCaptureProvider(backend=backend), CaptureOptions(monitor=1))

    assert backend.captured_region == regions[1]


def test_invalid_monitor_is_reported_safely() -> None:
    provider = MSSScreenCaptureProvider(backend=FakeScreenshotBackend([CaptureRegion(0, 0, 1, 1)]))

    with pytest.raises(ScreenCaptureError, match="monitor 3 is unavailable"):
        capture(provider, CaptureOptions(monitor=3))


def test_active_window_capture_uses_injected_region_provider() -> None:
    window = CaptureRegion(5, 6, 2, 2)
    backend = FakeScreenshotBackend([CaptureRegion(0, 0, 10, 10)])
    provider = MSSScreenCaptureProvider(
        backend=backend,
        active_window_provider=FakeActiveWindowProvider(window),
    )

    observation = capture(provider, CaptureOptions(active_window=True))

    assert backend.captured_region == window
    assert (observation.origin_x, observation.origin_y) == (5, 6)


def test_active_window_capture_is_explicitly_unsupported_without_provider() -> None:
    provider = MSSScreenCaptureProvider(backend=FakeScreenshotBackend([]))

    with pytest.raises(UnsupportedPlatformError, match="active-window"):
        capture(provider, CaptureOptions(active_window=True))


def test_backend_failure_is_translated() -> None:
    backend = FakeScreenshotBackend([CaptureRegion(0, 0, 1, 1)])
    backend.error = RuntimeError("driver internals")

    with pytest.raises(ScreenCaptureError, match="processing failed") as raised:
        capture(MSSScreenCaptureProvider(backend=backend))

    assert isinstance(raised.value.__cause__, RuntimeError)


def test_coordinate_mapping_accounts_for_resize_and_region_origin() -> None:
    backend = FakeScreenshotBackend([CaptureRegion(100, 50, 200, 100)])
    observation = capture(
        MSSScreenCaptureProvider(backend=backend),
        CaptureOptions(max_width=100, max_height=50),
    )

    assert image_to_screen_coordinates(50, 25, observation) == (200, 100)
    assert screen_to_image_coordinates(200, 100, observation) == (50, 25)


def test_coordinate_mapping_rejects_out_of_bounds_values() -> None:
    backend = FakeScreenshotBackend([CaptureRegion(10, 10, 2, 2)])
    observation = capture(MSSScreenCaptureProvider(backend=backend))

    with pytest.raises(ActionValidationError, match="image coordinate"):
        image_to_screen_coordinates(2, 0, observation)
    with pytest.raises(ActionValidationError, match="screen coordinate"):
        screen_to_image_coordinates(9, 10, observation)
