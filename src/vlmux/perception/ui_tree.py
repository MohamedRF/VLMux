"""Accessibility-tree snapshots with stable element references.

This module implements the provider-independent half of what agent-desktop
popularized: a desktop is captured as a tree of accessibility elements, each
actionable element receives a reference token like ``@s1a2b3:e8``, and the
agent acts on the reference instead of raw pixel coordinates.

Design rules (matching the agent-desktop model):

* **Refs belong to their snapshot.** Every refresh mints a new
  ``snapshot_id``; references from an older snapshot are rejected with
  :class:`vlmux.exceptions.StaleRefError` so the agent takes a new
  snapshot instead of clicking a phantom control.
* **Refs survive process boundaries.** :class:`RefRegistry` can persist a
  snapshot to disk and reload it in a later one-shot CLI invocation, matching
  how ``vlmux snapshot`` and ``vlmux click`` are used by agents.
* **Matching is deterministic.** Resolution re-walks the live tree and
  matches on ``(role, name, automation_id)`` plus the element's occurrence
  index within that key group. Nothing about intermediate UI state is
  trusted silently.
* **Providers are pluggable.** Windows ships a UI Automation provider
  (``vlmux[uia]``); other platforms can implement :class:`UITreeProvider`
  and register it behind the same interface.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from vlmux.exceptions import StaleRefError

_REF_PATTERN = re.compile(r"^@([A-Za-z0-9][A-Za-z0-9_-]{0,31}):e([0-9]{1,7})$")
_SNAPSHOT_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_snapshot_id() -> str:
    """Return a short, collision-resistant snapshot identifier."""

    return "".join(secrets.choice(_SNAPSHOT_ALPHABET) for _ in range(8))


@dataclass(frozen=True, slots=True)
class UITreeElement:
    """One accessibility-tree element, optionally holding a live control.

    ``live`` carries the provider-native handle (for example a UI Automation
    control) when the element was produced in-process; it is never serialized.
    """

    role: str
    name: str
    automation_id: str = ""
    path: tuple[int, ...] = ()
    bounds: tuple[int, int, int, int] | None = None
    available_actions: tuple[str, ...] = ()
    occurrence: int = 0
    live: Any | None = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> tuple[str, str, str, int]:
        """Stable match key: role, name, automation id, occurrence index."""

        return (self.role.casefold(), self.name, self.automation_id, self.occurrence)

    def ref_token(self, snapshot_id: str, index: int) -> str:
        """Return the reference token for this element within a snapshot."""

        return f"@{snapshot_id}:e{index}"

    def to_dict(self, ref: str | None = None) -> dict[str, Any]:
        """Return a JSON-serializable view of the element."""

        payload: dict[str, Any] = {
            "role": self.role,
            "name": self.name,
            "automation_id": self.automation_id or None,
            "path": list(self.path),
            "bounds": (
                {
                    "x": self.bounds[0],
                    "y": self.bounds[1],
                    "width": self.bounds[2],
                    "height": self.bounds[3],
                }
                if self.bounds is not None
                else None
            ),
            "available_actions": list(self.available_actions),
        }
        if ref is not None:
            payload["ref"] = ref
        return payload


@dataclass(slots=True)
class UITreeSnapshot:
    """One captured accessibility tree with registry-minted references."""

    snapshot_id: str
    captured_at: datetime
    source: str
    window_filter: str | None
    interactive_only: bool
    complete: bool
    elements: list[UITreeElement]
    refs: dict[str, int]  # ref token -> index into ``elements``

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable snapshot payload."""

        return {
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at.isoformat(),
            "source": self.source,
            "window_filter": self.window_filter,
            "interactive_only": self.interactive_only,
            "complete": self.complete,
            "ref_count": len(self.refs),
            "elements": [
                element.to_dict(ref=ref)
                for ref, index in self.refs.items()
                for element in [self.elements[index]]
            ],
        }

    def render_lines(self, *, max_chars: int = 6000) -> str:
        """Render a compact, prompt-friendly listing of interactive elements."""

        lines: list[str] = []
        size = 0
        truncated = False
        for ref, index in self.refs.items():
            element = self.elements[index]
            name = element.name.replace("\n", " ").strip()
            line = f'- {element.role} "{name}" [{ref}]'
            if element.available_actions:
                line += f" (actions: {', '.join(element.available_actions)})"
            if size + len(line) + 1 > max_chars:
                truncated = True
                break
            lines.append(line)
            size += len(line) + 1
        if truncated:
            lines.append("- … (additional elements truncated; use --compact or narrow --window-id)")
        return "\n".join(lines)


class UITreeProvider(Protocol):
    """Walk the accessibility tree of the desktop or one window."""

    def snapshot(
        self,
        *,
        window_id: str | None = None,
        app: str | None = None,
        interactive_only: bool = True,
        max_elements: int = 500,
    ) -> UITreeSnapshot:
        """Capture one snapshot; element ``live`` handles belong to this process."""
        ...

    def find(
        self, key: tuple[str, str, str, int], *, interactive_only: bool = True
    ) -> UITreeElement | None:
        """Re-walk the tree and return the live element matching ``key``, if any.

        ``key`` is ``(role.casefold(), name, automation_id, occurrence)``; the
        ``occurrence`` component counts elements sharing ``(role, name,
        automation_id)`` in deterministic depth-first order. ``interactive_only``
        must match the filter used at snapshot time or occurrence indices will
        not line up.
        """
        ...

    def click(self, element: UITreeElement, *, button: str = "left", clicks: int = 1) -> None:
        """Activate one element through headless accessibility APIs."""
        ...

    def set_value(self, element: UITreeElement, value: str) -> None:
        """Set one element's value through headless accessibility APIs."""
        ...


INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "splitbutton",
        "checkbox",
        "radio",
        "edit",
        "combobox",
        "listitem",
        "treeitem",
        "tabitem",
        "menuitem",
        "hyperlink",
        "slider",
        "spinner",
        "dataitem",
        "link",
        "togglebutton",
        "switch",
        "searchbox",
        "textfield",
    }
)


def is_interactive(role: str, available_actions: tuple[str, ...]) -> bool:
    """Return True for elements an agent can meaningfully act on."""

    if role.casefold() in INTERACTIVE_ROLES:
        return True
    return any(action != "Focus" for action in available_actions)


def assign_occurrences(elements: list[UITreeElement]) -> list[UITreeElement]:
    """Number elements that share a key so duplicates stay distinguishable."""

    seen: dict[tuple[str, str, str], int] = {}
    numbered: list[UITreeElement] = []
    for element in elements:
        base = (element.role.casefold(), element.name, element.automation_id)
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        if ordinal != element.occurrence:
            element = UITreeElement(
                role=element.role,
                name=element.name,
                automation_id=element.automation_id,
                path=element.path,
                bounds=element.bounds,
                available_actions=element.available_actions,
                occurrence=ordinal,
                live=element.live,
            )
        numbered.append(element)
    return numbered


class RefRegistry:
    """Mint, resolve, persist, and reload element reference tokens."""

    def __init__(self, *, cache_dir: Path | None = None, keep_snapshots: int = 8) -> None:
        self._cache_dir = cache_dir
        self._keep = keep_snapshots
        self._snapshots: dict[str, dict[str, tuple[str, str, str, int]]] = {}
        self._meta: dict[str, bool] = {}  # snapshot_id -> interactive_only

    @staticmethod
    def parse_ref(ref: str) -> tuple[str, int]:
        """Split ``@<snapshot_id>:e<index>`` into its parts."""

        match = _REF_PATTERN.match(ref)
        if match is None:
            raise StaleRefError(f"malformed element reference {ref!r}; take a fresh snapshot")
        return match.group(1), int(match.group(2))

    def register(
        self,
        elements: list[UITreeElement],
        *,
        source: str,
        interactive_only: bool,
        window_filter: str | None,
        complete: bool,
        snapshot_id: str | None = None,
    ) -> UITreeSnapshot:
        """Assign a fresh snapshot id and refs; persist for one-shot CLIs."""

        sid = snapshot_id or new_snapshot_id()
        refs = {element.ref_token(sid, index + 1): index for index, element in enumerate(elements)}
        snapshot = UITreeSnapshot(
            snapshot_id=sid,
            captured_at=datetime.now(UTC),
            source=source,
            window_filter=window_filter,
            interactive_only=interactive_only,
            complete=complete,
            elements=elements,
            refs=refs,
        )
        self._snapshots[sid] = snapshot_keys(snapshot)
        self._meta[sid] = interactive_only
        if self._cache_dir is not None:
            self._persist(snapshot)
        return snapshot

    def refs(self, snapshot_id: str) -> dict[str, tuple[str, str, str, int]] | None:
        """Return the stored ref→key mapping for a snapshot, if known."""

        cached = self._snapshots.get(snapshot_id)
        if cached is not None:
            return cached
        return self._load_cache(snapshot_id)

    def interactive_only(self, snapshot_id: str) -> bool:
        """Return the filter used when the snapshot was minted (default True)."""

        return self._meta.get(snapshot_id, True)

    def resolve(self, ref: str, provider: UITreeProvider) -> UITreeElement:
        """Resolve ``ref`` to a live element or raise a typed failure."""

        snapshot_id, _index = self.parse_ref(ref)
        keys = self.refs(snapshot_id)
        if keys is None:
            raise StaleRefError(
                f"unknown snapshot {snapshot_id!r}; take a fresh snapshot before acting"
            )
        key = keys.get(ref)
        if key is None:
            raise StaleRefError(f"reference {ref} is not present in snapshot {snapshot_id!r}")
        try:
            element = provider.find(key, interactive_only=self.interactive_only(snapshot_id))
        except Exception as error:  # provider implementations vary in failure modes
            raise StaleRefError(f"element {ref} could not be re-located: {error}") from error
        if element is None:
            raise StaleRefError(
                f"element {ref} no longer exists; take a fresh snapshot before acting"
            )
        return element

    def _persist(self, snapshot: UITreeSnapshot) -> None:
        assert self._cache_dir is not None
        cache_dir = self._cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at.isoformat(),
            "source": snapshot.source,
            "window_filter": snapshot.window_filter,
            "interactive_only": snapshot.interactive_only,
            "keys": {ref: list(key) for ref, key in snapshot_keys(snapshot).items()},
        }
        path = cache_dir / f"{snapshot.snapshot_id}.json"
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
            if os.name == "posix":
                os.chmod(path, 0o600)
        except OSError:
            pass  # caching is best-effort; resolution falls back to in-memory state
        self._prune(cache_dir)

    def _load_cache(self, snapshot_id: str) -> dict[str, tuple[str, str, str, int]] | None:
        if self._cache_dir is None:
            return None
        path = self._cache_dir / f"{snapshot_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        keys = payload.get("keys")
        if not isinstance(keys, dict):
            return None
        parsed: dict[str, tuple[str, str, str, int]] = {}
        for ref, key in keys.items():
            if (
                isinstance(ref, str)
                and isinstance(key, list)
                and len(key) == 4
                and isinstance(key[3], int)
            ):
                parsed[ref] = (str(key[0]), str(key[1]), str(key[2]), key[3])
        self._snapshots[snapshot_id] = parsed
        self._meta[snapshot_id] = bool(payload.get("interactive_only", True))
        return parsed

    def _prune(self, cache_dir: Path) -> None:
        try:
            snapshots = sorted(
                cache_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
            )
        except OSError:
            return
        for path in snapshots[self._keep :]:
            with contextlib.suppress(OSError):
                path.unlink()


def snapshot_keys(snapshot: UITreeSnapshot) -> dict[str, tuple[str, str, str, int]]:
    """Return the ref→match-key mapping carried by a snapshot."""

    result: dict[str, tuple[str, str, str, int]] = {}
    for ref, index in snapshot.refs.items():
        element = snapshot.elements[index]
        result[ref] = element.key
    return result
