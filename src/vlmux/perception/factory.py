"""Central construction of platform-aware screen capture providers."""

import platform

from vlmux.perception.base import ScreenCaptureProvider
from vlmux.perception.mss_provider import MSSScreenCaptureProvider


def create_screen_capture_provider(*, system_name: str | None = None) -> ScreenCaptureProvider:
    """Create the native capture provider without platform checks in callers."""
    current_system = system_name or platform.system()
    if current_system == "Windows":
        from vlmux.perception.windows import WindowsActiveWindowRegionProvider
        from vlmux.platforms.windows import enable_dpi_awareness

        enable_dpi_awareness()
        return MSSScreenCaptureProvider(
            active_window_provider=WindowsActiveWindowRegionProvider(),
        )
    return MSSScreenCaptureProvider()
