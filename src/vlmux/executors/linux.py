"""Linux desktop executor backed by pynput and ``xdg-open``."""

from __future__ import annotations

import subprocess
from typing import ClassVar

from vlmux.executors.posix import PosixExecutor, PosixInputBackend, PynputPosixBackend


class LinuxBackend(PynputPosixBackend):
    """Linux input backend with shell-free application launching."""

    _app_aliases: ClassVar[dict[str, str]] = {
        "calculator": "gnome-calculator",
        "calc": "gnome-calculator",
        "notepad": "gedit",
        "textedit": "gedit",
        "terminal": "gnome-terminal",
    }

    def open_app(self, application: str, arguments: list[str]) -> None:
        executable = self._app_aliases.get(application.strip().casefold(), application)
        subprocess.Popen(
            [executable, *arguments],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )


class LinuxExecutor(PosixExecutor):
    """Execute desktop input on Linux."""

    platform_name = "Linux"

    def __init__(self, *, backend: PosixInputBackend | None = None) -> None:
        super().__init__(backend=backend or LinuxBackend())
