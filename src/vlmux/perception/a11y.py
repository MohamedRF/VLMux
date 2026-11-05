"""Accessibility-tree perception: screenshot plus structured window metadata.

The provider boundary is pluggable. The Windows backend enumerates top-level
windows through user32 and reports them as an accessibility tree with window
nodes; full UI Automation control discovery can be added behind the same
protocol. Other platforms expose the window list through their executors.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Protocol

from vlmux.core import WindowInfo
from vlmux.exceptions import UnsupportedPlatformError


class AccessibilityProvider(Protocol):
    """Return a structured accessibility tree for the current desktop."""

    def tree(self) -> dict[str, Any]:
        """Return a JSON-serializable tree; window nodes carry title and bounds."""
        ...


class WindowListProvider(Protocol):
    """List desktop windows as VLMux window infos."""

    def list_windows(self) -> list[WindowInfo]:
        """Return visible windows."""
        ...


class WindowsWindowListProvider:
    """Enumerate top-level Windows windows through user32."""

    def list_windows(self) -> list[WindowInfo]:
        """Return visible top-level windows with titles and bounds."""
        try:
            windows_library = vars(ctypes)["WinDLL"]
            winfunctype = vars(ctypes)["WINFUNCTYPE"]
        except KeyError as error:
            raise UnsupportedPlatformError("window listing requires Windows") from error
        user32 = windows_library("user32", use_last_error=True)
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND

        windows: list[WindowInfo] = []
        foreground = user32.GetForegroundWindow()

        _callback_t = winfunctype(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd: wintypes.HWND, _param: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            rectangle = wintypes.RECT()
            left = top = width = height = None
            if user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
                left, top = rectangle.left, rectangle.top
                width = rectangle.right - rectangle.left
                height = rectangle.bottom - rectangle.top
            windows.append(
                WindowInfo(
                    id=str(hwnd),
                    title=title,
                    focused=(hwnd == foreground),
                    x=left,
                    y=top,
                    width=width,
                    height=height,
                )
            )
            return True

        user32.EnumWindows(_callback_t(_callback), 0)
        return windows


class WindowsA11yProvider:
    """Accessibility tree backed by the Windows window list."""

    def __init__(self, window_provider: WindowListProvider | None = None) -> None:
        self._windows = window_provider or WindowsWindowListProvider()

    def tree(self) -> dict[str, Any]:
        """Build a tree whose children are the visible windows."""
        windows = self._windows.list_windows()
        return {
            "role": "application",
            "name": "desktop",
            "children": [
                {
                    "role": "window",
                    "name": window.title,
                    "window_id": window.id,
                    "focused": window.focused,
                    "bounds": {
                        "x": window.x,
                        "y": window.y,
                        "width": window.width,
                        "height": window.height,
                    },
                }
                for window in windows
            ],
        }
