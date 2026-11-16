"""Central platform selection for desktop execution."""

import platform
from typing import Any

from vlmux.exceptions import UnsupportedPlatformError
from vlmux.executors.base import ComputerExecutor


def create_computer_executor(
    *,
    system_name: str | None = None,
    ui_registry: Any | None = None,
    ui_provider: Any | None = None,
) -> ComputerExecutor:
    """Create the supported executor for the current operating system.

    ``ui_registry``/``ui_provider`` enable ref-based actions; when omitted,
    ref actions fail closed with :class:`RefUnavailableError`.
    """
    current_system = system_name or platform.system()
    if current_system == "Windows":
        from vlmux.executors.windows import WindowsExecutor

        return WindowsExecutor(ui_registry=ui_registry, ui_provider=ui_provider)
    if current_system == "Darwin":
        from vlmux.executors.macos import MacOSExecutor

        return MacOSExecutor()
    if current_system == "Linux":
        from vlmux.executors.linux import LinuxExecutor

        return LinuxExecutor()
    raise UnsupportedPlatformError(f"desktop control is not supported on {current_system}")
