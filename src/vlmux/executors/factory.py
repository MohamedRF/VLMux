"""Central platform selection for desktop execution."""

import platform

from vlmux.exceptions import UnsupportedPlatformError
from vlmux.executors.base import ComputerExecutor


def create_computer_executor(*, system_name: str | None = None) -> ComputerExecutor:
    """Create the supported executor for the current operating system."""
    current_system = system_name or platform.system()
    if current_system == "Windows":
        from vlmux.executors.windows import WindowsExecutor

        return WindowsExecutor()
    raise UnsupportedPlatformError(f"desktop control is not supported on {current_system}")
