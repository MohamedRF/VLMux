"""Tests for accessibility-tree snapshots and element references."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlmux.exceptions import StaleRefError
from vlmux.perception.ui_tree import (
    RefRegistry,
    UITreeElement,
    assign_occurrences,
    is_interactive,
    new_snapshot_id,
)


def _element(
    role: str,
    name: str,
    automation_id: str = "",
    actions: tuple[str, ...] = ("Click",),
    bounds: tuple[int, int, int, int] = (0, 0, 10, 10),
) -> UITreeElement:
    return UITreeElement(
        role=role,
        name=name,
        automation_id=automation_id,
        bounds=bounds,
        available_actions=actions,
    )


class FakeProvider:
    """In-memory provider matching keys against a fixed element list."""

    def __init__(self, elements: list[UITreeElement]) -> None:
        self.elements = assign_occurrences(elements)

    def find(
        self, key: tuple[str, str, str, int], *, interactive_only: bool = True
    ) -> UITreeElement | None:
        for element in self.elements:
            if element.key == key:
                return element
        return None


def _snapshot(registry: RefRegistry, elements: list[UITreeElement]):
    return registry.register(
        assign_occurrences(elements),
        source="test",
        interactive_only=True,
        window_filter=None,
        complete=True,
    )


def test_register_assigns_ordered_refs() -> None:
    registry = RefRegistry()
    snapshot = _snapshot(registry, [_element("button", "Save"), _element("edit", "Name")])

    assert list(snapshot.refs) == [
        f"@{snapshot.snapshot_id}:e1",
        f"@{snapshot.snapshot_id}:e2",
    ]
    assert snapshot.to_dict()["ref_count"] == 2


def test_resolve_roundtrip() -> None:
    elements = [_element("button", "Save", "saveBtn"), _element("edit", "Name", "")]
    registry = RefRegistry()
    snapshot = _snapshot(registry, elements)
    provider = FakeProvider(elements)

    ref = f"@{snapshot.snapshot_id}:e1"
    resolved = registry.resolve(ref, provider)

    assert resolved.name == "Save"
    assert resolved.automation_id == "saveBtn"


def test_resolve_stale_when_element_gone() -> None:
    elements = [_element("button", "Save", "saveBtn")]
    registry = RefRegistry()
    snapshot = _snapshot(registry, elements)
    provider = FakeProvider([])  # desktop changed: nothing to find

    with pytest.raises(StaleRefError) as exc_info:
        registry.resolve(f"@{snapshot.snapshot_id}:e1", provider)
    assert exc_info.value.code == "stale_ref"


def test_resolve_stale_when_snapshot_unknown() -> None:
    registry = RefRegistry()
    with pytest.raises(StaleRefError):
        registry.resolve("@deadbeef:e1", FakeProvider([]))


def test_resolve_stale_when_ref_not_in_snapshot() -> None:
    registry = RefRegistry()
    snapshot = _snapshot(registry, [_element("button", "Save")])
    with pytest.raises(StaleRefError):
        registry.resolve(f"@{snapshot.snapshot_id}:e9", FakeProvider([]))


def test_malformed_ref_is_stale_ref_error() -> None:
    registry = RefRegistry()
    with pytest.raises(StaleRefError):
        registry.parse_ref("button-Save")


def test_occurrence_indexing_distinguishes_duplicates() -> None:
    elements = [
        _element("button", "Open", ""),
        _element("button", "Open", ""),
        _element("button", "Save", ""),
    ]
    registry = RefRegistry()
    snapshot = _snapshot(registry, elements)
    provider = FakeProvider(elements)

    keys = list(snapshot.refs)
    first = registry.resolve(keys[0], provider)
    second = registry.resolve(keys[1], provider)

    assert (first.key[3], second.key[3]) == (0, 1)


def test_registry_persistence_roundtrip(tmp_path: Path) -> None:
    elements = [_element("button", "Save", "saveBtn")]
    writer = RefRegistry(cache_dir=tmp_path)
    snapshot = _snapshot(writer, elements)

    persisted = list(tmp_path.glob("*.json"))
    assert len(persisted) == 1
    payload = json.loads(persisted[0].read_text(encoding="utf-8"))
    assert payload["snapshot_id"] == snapshot.snapshot_id

    # Simulate a one-shot CLI process: fresh registry, no memory of the write.
    reader = RefRegistry(cache_dir=tmp_path)
    provider = FakeProvider(elements)
    resolved = reader.resolve(f"@{snapshot.snapshot_id}:e1", provider)
    assert resolved.name == "Save"


def test_resolve_with_corrupt_cache_returns_stale(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    reader = RefRegistry(cache_dir=tmp_path)
    with pytest.raises(StaleRefError):
        reader.resolve("@broken:e1", FakeProvider([]))


def test_registry_prunes_old_snapshots(tmp_path: Path) -> None:
    writer = RefRegistry(cache_dir=tmp_path, keep_snapshots=2)
    elements = [_element("button", "Go")]
    for _ in range(4):
        _snapshot(writer, elements)
    remaining = sorted(tmp_path.glob("*.json"))
    assert len(remaining) == 2


def test_render_lines_contains_refs_and_actions() -> None:
    registry = RefRegistry()
    snapshot = _snapshot(registry, [_element("button", "Save", "saveBtn", ("Click",))])
    text = snapshot.render_lines()

    assert 'button "Save"' in text
    assert f"@{snapshot.snapshot_id}:e1" in text
    assert "Click" in text


def test_render_lines_truncates_long_trees() -> None:
    elements = [_element("button", f"Button {index:04d}", "") for index in range(50)]
    registry = RefRegistry()
    snapshot = _snapshot(registry, elements)
    text = snapshot.render_lines(max_chars=200)

    assert "truncated" in text


def test_snapshot_id_format() -> None:
    snapshot_id = new_snapshot_id()
    assert len(snapshot_id) == 8
    assert snapshot_id.isalnum()


@pytest.mark.parametrize(
    ("role", "actions", "expected"),
    [
        ("button", (), True),
        ("edit", ("SetValue",), True),
        ("text", (), False),
        ("label", ("Focus",), False),
        ("menuitem", (), True),
        ("listitem", (), True),
    ],
)
def test_is_interactive(role: str, actions: tuple[str, ...], expected: bool) -> None:
    assert is_interactive(role, actions) is expected
