"""macOS desktop executor backed by pynput and the native ``open`` command."""

from __future__ import annotations

import subprocess
from typing import ClassVar

from vlmux.executors.posix import PosixExecutor, PosixInputBackend, PynputPosixBackend


class MacOSBackend(PynputPosixBackend):
    """macOS input backend with native application launching."""

    _app_aliases: ClassVar[dict[str, str]] = {
        "calculator": "Calculator",
        "calc": "Calculator",
        "notepad": "TextEdit",
        "textedit": "TextEdit",
        "terminal": "Terminal",
    }

    def open_app(self, application: str, arguments: list[str]) -> None:
        name = self._app_aliases.get(application.strip().casefold(), application)
        command = ["open", "-a", name, *arguments]
        subprocess.Popen(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )


class MacOSExecutor(PosixExecutor):
    """Execute desktop input on macOS."""

    platform_name = "macOS"

    def __init__(self, *, backend: PosixInputBackend | None = None) -> None:
        super().__init__(backend=backend or MacOSBackend())
