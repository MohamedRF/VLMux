"""Windows UI Automation accessibility-tree provider.

Implements :class:`vlmux.perception.ui_tree.UITreeProvider` on top of the UI
Automation API through the optional ``uiautomation`` package
(``pip install vlmux[uia]``). All element invocation is headless: the pointer
is never moved and focus is never stolen; actions use UIA patterns only.

The provider is imported lazily so non-Windows installs never pay the import
cost, and missing dependencies surface as a clear error instead of a crash.
"""

from __future__ import annotations

import contextlib
import platform
from pathlib import Path
from typing import Any

from vlmux.exceptions import (
    ActionExecutionError,
    AmbiguousTargetError,
    HeadlessActionNotSupportedError,
    ScreenCaptureError,
    UnsupportedPlatformError,
)
from vlmux.perception.ui_tree import (
    RefRegistry,
    UITreeElement,
    UITreeSnapshot,
    assign_occurrences,
    is_interactive,
    new_snapshot_id,
)

_ROLE_RENAMES = {
    "radiobutton": "radio",
    "togglebutton": "togglebutton",
    "splitbutton": "splitbutton",
    "hyperlink": "hyperlink",
    "edit": "edit",
    "searchbox": "searchbox",
}


def _ensure_com_initialized() -> None:
    """Initialize COM for this worker thread, once per thread.

    UI Automation requires per-thread ``CoInitialize``. COM object references
    (stored in snapshot/resolved elements) are only valid for the apartment
    that created them, and they outlive the call that produced them — so the
    apartment is intentionally kept alive for the thread's lifetime rather
    than torn down per call. ``CoInitialize`` is refcounted; repeated calls
    in the same thread are cheap and legal.

    Uses the COM entry point through ctypes so no extra dependency surface is
    needed here. UI Automation itself still needs ``uiautomation``/``comtypes``.
    """

    import ctypes

    with contextlib.suppress(Exception):
        ctypes.windll.ole32.CoInitialize(None)


def _role_of(control_type_name: str) -> str:
    role = control_type_name.removesuffix("Control").casefold()
    return _ROLE_RENAMES.get(role, role)


def _bounds_of(rectangle: Any) -> tuple[int, int, int, int] | None:
    try:
        width = int(rectangle.right - rectangle.left)
        height = int(rectangle.bottom - rectangle.top)
        if width <= 0 or height <= 0:
            return None
        return (int(rectangle.left), int(rectangle.top), width, height)
    except (TypeError, ValueError, AttributeError):
        return None


def _actions_of(control: Any) -> tuple[str, ...]:
    actions: list[str] = []
    probes = (
        ("GetInvokePattern", "Click"),
        ("GetTogglePattern", "Toggle"),
        ("GetValuePattern", "SetValue"),
        ("GetSelectionItemPattern", "Select"),
        ("GetExpandCollapsePattern", "Expand"),
    )
    for method_name, action in probes:
        getter = getattr(control, method_name, None)
        if getter is None:
            continue
        try:
            pattern = getter()
        except Exception:
            pattern = None
        if pattern:
            actions.append(action)
    return tuple(actions)


def _walk_window(window: Any, *, path: tuple[int, ...] = ()) -> list[UITreeElement]:
    """Depth-first enumerate elements under one top-level window."""

    elements: list[UITreeElement] = []
    try:
        children = window.GetChildren()
    except Exception:
        return elements
    for index, child in enumerate(children):
        child_path = (*path, index)
        try:
            name = (child.Name or "").strip()
        except Exception:
            name = ""
        try:
            automation_id = (child.AutomationId or "") or ""
        except Exception:
            automation_id = ""
        try:
            role = _role_of(child.ControlTypeName or "")
        except Exception:
            role = ""
        try:
            bounds = _bounds_of(child.BoundingRectangle)
        except Exception:
            bounds = None
        actions = _actions_of(child)
        if bounds is not None:
            elements.append(
                UITreeElement(
                    role=role,
                    name=name,
                    automation_id=automation_id,
                    path=child_path,
                    bounds=bounds,
                    available_actions=actions,
                    live=child,
                )
            )
        elements.extend(_walk_window(child, path=child_path))
    return elements


class WindowsUITreeProvider:
    """Capture and resolve Windows accessibility snapshots via UI Automation."""

    def __init__(self, registry: RefRegistry) -> None:

        if platform.system() != "Windows":
            raise UnsupportedPlatformError("accessibility snapshots are currently Windows-only")
        try:
            import uiautomation
        except ImportError as error:
            raise UnsupportedPlatformError(
                "Windows accessibility snapshots require the 'uiautomation' package; "
                "install it with: pip install vlmux[uia]"
            ) from error
        self._auto = uiautomation
        self._registry = registry

    # -- capture ---------------------------------------------------------

    def _top_level_windows(self, window_id: str | None, app: str | None) -> list[Any]:
        auto = self._auto
        root = auto.GetRootControl()
        candidates = list(root.GetChildren())
        if window_id is not None:
            try:
                handle = int(window_id)
            except ValueError as error:
                raise ScreenCaptureError(
                    f"window_id {window_id!r} is not a numeric window handle"
                ) from error
            control = auto.ControlFromHandle(handle)
            if control is None:
                raise ScreenCaptureError(f"no window exists with id {window_id!r}")
            return [control]
        windows = [
            child
            for child in candidates
            if _role_of(getattr(child, "ControlTypeName", "") or "") == "window"
            and _bounds_of(getattr(child, "BoundingRectangle", None)) is not None
        ]
        if app is not None:
            needle = app.casefold()
            windows = [window for window in windows if needle in (window.Name or "").casefold()]
            if not windows:
                raise ScreenCaptureError(f"no visible window matches {app!r}")
            if len(windows) > 1:
                names = ", ".join(sorted((window.Name or "")[:40] for window in windows[:5]))
                raise AmbiguousTargetError(
                    f"{len(windows)} windows match {app!r} ({names}); pass --window-id instead"
                )
        return windows

    def _flatten(
        self,
        *,
        window_id: str | None,
        app: str | None,
        interactive_only: bool,
        max_elements: int | None,
    ) -> tuple[list[UITreeElement], bool]:
        windows = self._top_level_windows(window_id, app)
        elements: list[UITreeElement] = []
        complete = True
        for window in windows:
            for element in _walk_window(window):
                if interactive_only and not is_interactive(element.role, element.available_actions):
                    continue
                elements.append(element)
                if max_elements is not None and len(elements) >= max_elements:
                    complete = False
                    break
            if not complete:
                break
        return assign_occurrences(elements), complete

    def snapshot(
        self,
        *,
        window_id: str | None = None,
        app: str | None = None,
        interactive_only: bool = True,
        max_elements: int = 500,
    ) -> UITreeSnapshot:
        """Capture one UIA snapshot and register refs with the shared registry."""

        _ensure_com_initialized()
        elements, complete = self._flatten(
            window_id=window_id,
            app=app,
            interactive_only=interactive_only,
            max_elements=max_elements,
        )
        return self._registry.register(
            elements,
            source="windows-uia",
            interactive_only=interactive_only,
            window_filter=window_id or app,
            complete=complete,
            snapshot_id=new_snapshot_id(),
        )

    # -- resolution --------------------------------------------------------

    def find(
        self, key: tuple[str, str, str, int], *, interactive_only: bool = True
    ) -> UITreeElement | None:
        """Re-walk the tree and return the live element matching ``key``."""

        _ensure_com_initialized()
        elements, _complete = self._flatten(
            window_id=None,
            app=None,
            interactive_only=interactive_only,
            max_elements=None,
        )
        for element in elements:
            if element.key == key:
                return element
        return None

    # -- headless action invocation -----------------------------------------

    def click(self, element: UITreeElement, *, button: str = "left", clicks: int = 1) -> None:
        """Activate one element through UIA patterns (never moves the pointer)."""

        _ensure_com_initialized()
        if button != "left":
            raise HeadlessActionNotSupportedError(
                f"headless UIA activation supports only the left button, got {button!r}; "
                "use mouse actions for middle/right clicks"
            )
        if clicks != 1:
            raise HeadlessActionNotSupportedError(
                f"headless UIA activation invokes once per call, got clicks={clicks}; "
                "use a mouse double-click instead"
            )
        control = element.live
        if control is None:
            raise ActionExecutionError("element has no live control handle; re-resolve it first")
        for method_name in ("GetInvokePattern", "GetTogglePattern", "GetSelectionItemPattern"):
            getter = getattr(control, method_name, None)
            if getter is None:
                continue
            try:
                pattern = getter()
            except Exception:
                pattern = None
            if not pattern:
                continue
            try:
                if method_name == "GetTogglePattern":
                    pattern.Toggle()
                elif method_name == "GetSelectionItemPattern":
                    pattern.Select()
                else:
                    pattern.Invoke()
                return
            except Exception as error:
                raise ActionExecutionError(f"headless activation failed: {error}") from error
        raise HeadlessActionNotSupportedError(
            f"element {element.role!r} ({element.name!r}) exposes no headless action pattern; "
            "take a fresh snapshot or use coordinate actions"
        )

    def set_value(self, element: UITreeElement, value: str) -> None:
        """Set one element's value through the UIA Value pattern."""

        _ensure_com_initialized()
        control = element.live
        if control is None:
            raise ActionExecutionError("element has no live control handle; re-resolve it first")
        getter = getattr(control, "GetValuePattern", None)
        pattern = None
        if getter is not None:
            try:
                pattern = getter()
            except Exception:
                pattern = None
        if not pattern:
            raise HeadlessActionNotSupportedError(
                f"element {element.role!r} ({element.name!r}) does not accept a value headlessly; "
                "use click_ref followed by type"
            )
        try:
            read_only = bool(getattr(pattern, "IsReadOnly", False))
        except Exception:
            read_only = False
        if read_only:
            raise HeadlessActionNotSupportedError(f"element {element.name!r} is read-only")
        try:
            pattern.SetValue(value)
        except Exception as error:
            raise ActionExecutionError(f"failed to set value: {error}") from error


def default_registry(cache_dir: Path | None = None) -> RefRegistry:
    """Return a registry persisting snapshots under the user cache directory."""

    if cache_dir is None:
        from platformdirs import user_cache_path

        cache_dir = user_cache_path("vlmux", appauthor=False) / "snapshots"
    else:
        cache_dir = Path(cache_dir)
    return RefRegistry(cache_dir=cache_dir)
