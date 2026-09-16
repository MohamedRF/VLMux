"""Tests for centralized capture-provider platform selection."""

from vlmux.perception import MSSScreenCaptureProvider, create_screen_capture_provider


def test_factory_creates_cross_platform_full_screen_provider() -> None:
    provider = create_screen_capture_provider(system_name="Linux")

    assert isinstance(provider, MSSScreenCaptureProvider)


def test_windows_factory_adds_active_window_support() -> None:
    provider = create_screen_capture_provider(system_name="Windows")

    assert isinstance(provider, MSSScreenCaptureProvider)
    assert provider._active_window_provider is not None
