"""Shared Windows process configuration."""

import ctypes


def enable_dpi_awareness() -> None:
    """Use physical pixels so capture and input share one coordinate system."""
    try:
        windll = vars(ctypes)["windll"]
        windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, KeyError, OSError):
        try:
            windll = vars(ctypes)["windll"]
            windll.user32.SetProcessDPIAware()
        except (AttributeError, KeyError, OSError):
            return
