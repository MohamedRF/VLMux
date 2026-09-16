"""Installed-package integration smoke test."""

import vlmux


def test_public_version_is_available() -> None:
    assert vlmux.__version__ == "0.1.0"
