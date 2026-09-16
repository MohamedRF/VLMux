"""Desktop executor interfaces, factories, and platform implementations."""

from vlmux.executors.base import ComputerExecutor
from vlmux.executors.factory import create_computer_executor
from vlmux.executors.windows import PynputInputBackend, WindowsExecutor

__all__ = [
    "ComputerExecutor",
    "PynputInputBackend",
    "WindowsExecutor",
    "create_computer_executor",
]
