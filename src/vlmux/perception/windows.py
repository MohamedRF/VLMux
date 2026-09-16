"""Windows-specific perception helpers."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from vlmux.exceptions import ScreenCaptureError, UnsupportedPlatformError
from vlmux.perception.models import CaptureRegion


class WindowsActiveWindowRegionProvider:
    """Resolve the foreground window rectangle through user32."""

    def active_window_region(self) -> CaptureRegion:
        try:
            windows_library = vars(ctypes)["WinDLL"]
        except KeyError as error:
            raise UnsupportedPlatformError("active-window capture requires Windows") from error
        user32 = windows_library("user32", use_last_error=True)
        get_foreground_window = user32.GetForegroundWindow
        get_foreground_window.restype = wintypes.HWND
        get_window_rect = user32.GetWindowRect
        get_window_rect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        get_window_rect.restype = wintypes.BOOL

        window = get_foreground_window()
        if not window:
            raise ScreenCaptureError("no foreground window is available")
        rectangle = wintypes.RECT()
        if not get_window_rect(window, ctypes.byref(rectangle)):
            raise ScreenCaptureError("unable to read the foreground window bounds")
        return CaptureRegion(
            left=rectangle.left,
            top=rectangle.top,
            width=rectangle.right - rectangle.left,
            height=rectangle.bottom - rectangle.top,
        )
