"""Ref-action dispatch through the desktop executor with fakes."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from vlmux.exceptions import HeadlessActionNotSupportedError
from vlmux.executors.base import MouseButton
from vlmux.executors.windows import WindowsExecutor
from vlmux.perception.ui_tree import RefRegistry, UITreeElement, assign_occurrences
from vlmux.protocol import ClickRefAction, SetValueRefAction


class FakeBackend:
    """No-op input backend so the executor constructs without pynput."""

    def click(self, x: int, y: int, button: MouseButton, count: int, interval_ms: int) -> None:
        pass

    def move(self, x: int, y: int, duration_ms: int) -> None:
        pass

    def type_text(self, text: str, interval_ms: int) -> None:
        pass

    def press_key(self, key: str, presses: int, interval_ms: int) -> None:
        pass

    def hotkey(self, keys: list[str]) -> None:
        pass

    def scroll(self, delta_x: int, delta_y: int, x: int | None, y: int | None) -> None:
        pass

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
        button: MouseButton,
    ) -> None:
        pass

    def open_app(self, application: str, arguments: list[str]) -> None:
        pass


class FakeUIProvider:
    """In-memory UIA stand-in recording performed actions."""

    def __init__(self, elements: list[UITreeElement]) -> None:
        self.elements = assign_occurrences(elements)
        self.clicked: list[tuple[str, str]] = []
        self.values: list[tuple[str, str]] = []

    def find(
        self, key: tuple[str, str, str, int], *, interactive_only: bool = True
    ) -> UITreeElement | None:
        return next((element for element in self.elements if element.key == key), None)

    def click(self, element: UITreeElement, *, button: str = "left", clicks: int = 1) -> None:
        self.clicked.append((element.name, button))

    def set_value(self, element: UITreeElement, value: str) -> None:
        self.values.append((element.name, value))


def _fixture(
    elements: list[UITreeElement], *, wire: bool = True
) -> tuple[WindowsExecutor, FakeUIProvider, RefRegistry]:
    registry = RefRegistry()
    provider = FakeUIProvider(assign_occurrences(elements))
    registry.register(
        assign_occurrences(elements),
        source="test",
        interactive_only=True,
        window_filter=None,
        complete=True,
        snapshot_id="snap0001",
    )
    if wire:
        executor = WindowsExecutor(
            backend=FakeBackend(), ui_registry=registry, ui_provider=provider
        )
    else:
        executor = WindowsExecutor(backend=FakeBackend())
    return executor, provider, registry


def test_click_ref_invokes_element() -> None:
    elements = [
        UITreeElement(
            role="button",
            name="Save",
            automation_id="saveBtn",
            bounds=(0, 0, 10, 10),
            available_actions=("Click",),
        )
    ]
    executor, provider, _registry = _fixture(elements)

    result = asyncio.run(executor.execute(ClickRefAction(ref="@snap0001:e1")))

    assert result.success is True
    assert provider.clicked == [("Save", "left")]


def test_click_ref_stale_ref_returns_failure_code() -> None:
    # Register the ref at snapshot time, then simulate the desktop changing:
    # the live tree no longer contains the element.
    elements = [
        UITreeElement(
            role="button",
            name="Save",
            automation_id="saveBtn",
            bounds=(0, 0, 10, 10),
            available_actions=("Click",),
        )
    ]
    registry = RefRegistry()
    registry.register(
        assign_occurrences(elements),
        source="test",
        interactive_only=True,
        window_filter=None,
        complete=True,
        snapshot_id="snap0001",
    )
    provider = FakeUIProvider([])  # element is gone from the live tree
    executor = WindowsExecutor(backend=FakeBackend(), ui_registry=registry, ui_provider=provider)

    result = asyncio.run(executor.execute(ClickRefAction(ref="@snap0001:e1")))

    assert result.success is False
    assert result.error_code == "stale_ref"
    assert provider.clicked == []


def test_click_ref_without_ui_backend_fails_closed() -> None:
    executor = WindowsExecutor(backend=FakeBackend())

    result = asyncio.run(executor.execute(ClickRefAction(ref="@snap0001:e1")))

    assert result.success is False
    assert result.error_code == "ref_unavailable"


def test_set_value_ref_sets_value() -> None:
    elements = [
        UITreeElement(
            role="edit",
            name="Name",
            automation_id="nameBox",
            bounds=(0, 0, 100, 20),
            available_actions=("SetValue",),
        )
    ]
    executor, provider, _registry = _fixture(elements)

    result = asyncio.run(executor.execute(SetValueRefAction(ref="@snap0001:e1", value="Alice")))

    assert result.success is True
    assert provider.values == [("Name", "Alice")]


def test_headless_not_supported_maps_to_error_code() -> None:
    class NoPatternProvider(FakeUIProvider):
        def click(self, element: Any, *, button: str = "left", clicks: int = 1) -> None:
            raise HeadlessActionNotSupportedError("element exposes no pattern")

    elements = [
        UITreeElement(
            role="button",
            name="Nope",
            automation_id="",
            bounds=(0, 0, 1, 1),
            available_actions=(),
        )
    ]
    registry = RefRegistry()
    provider = NoPatternProvider(elements)
    registry.register(
        assign_occurrences(elements),
        source="test",
        interactive_only=True,
        window_filter=None,
        complete=True,
        snapshot_id="snap0002",
    )
    executor = WindowsExecutor(backend=FakeBackend(), ui_registry=registry, ui_provider=provider)

    result = asyncio.run(executor.execute(ClickRefAction(ref="@snap0002:e1")))

    assert result.success is False
    assert result.error_code == "headless_not_supported"


def test_set_value_ref_rejects_invalid_ref_shape() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClickRefAction(ref="saveButton")
