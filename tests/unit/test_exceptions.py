"""Tests for the public exception hierarchy."""

import inspect

import vlmux.exceptions as exceptions


def test_all_application_errors_derive_from_vlmux_error() -> None:
    error_types = [
        member
        for name, member in inspect.getmembers(exceptions, inspect.isclass)
        if name != "VLMuxError" and member.__module__ == exceptions.__name__
    ]

    assert error_types
    assert all(issubclass(error_type, exceptions.VLMuxError) for error_type in error_types)
