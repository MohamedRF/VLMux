"""Typed models for version 1.0 of the VLMux Action Protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

VAP_VERSION: Literal["1.0"] = "1.0"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class VAPModel(BaseModel):
    """Strict base model shared by all VAP payloads."""

    model_config = ConfigDict(extra="forbid")


class BaseAction(VAPModel):
    """Metadata common to every VAP action."""

    version: Literal["1.0"] = VAP_VERSION
    id: str | None = Field(default=None, min_length=1)
    timestamp: datetime = Field(default_factory=_utc_now)
    source_model: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous timestamps that have no UTC offset."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class CoordinateAction(BaseAction):
    """Base for actions targeting an absolute screen-pixel coordinate."""

    x: int
    y: int


class ClickAction(CoordinateAction):
    """Click the primary mouse button once."""

    type: Literal["click"] = "click"
    button: Literal["left", "middle"] = "left"


class DoubleClickAction(CoordinateAction):
    """Click the primary mouse button twice."""

    type: Literal["double_click"] = "double_click"
    interval_ms: int = Field(default=100, ge=0, le=1000)


class RightClickAction(CoordinateAction):
    """Click the secondary mouse button once."""

    type: Literal["right_click"] = "right_click"


class MoveCursorAction(CoordinateAction):
    """Move the pointer to an absolute screen-pixel coordinate."""

    type: Literal["move_cursor"] = "move_cursor"
    duration_ms: int = Field(default=0, ge=0, le=60_000)


class TypeAction(BaseAction):
    """Type text using keyboard input."""

    type: Literal["type"] = "type"
    text: str = Field(min_length=1)
    interval_ms: int = Field(default=0, ge=0, le=10_000)


class PasteAction(BaseAction):
    """Paste the supplied text through the platform clipboard."""

    type: Literal["paste"] = "paste"
    text: str = Field(min_length=1)


class KeyAction(BaseAction):
    """Press a named keyboard key one or more times."""

    type: Literal["key"] = "key"
    key: str = Field(min_length=1)
    presses: int = Field(default=1, ge=1, le=100)
    interval_ms: int = Field(default=0, ge=0, le=10_000)


class HotkeyAction(BaseAction):
    """Press a non-empty keyboard shortcut."""

    type: Literal["hotkey"] = "hotkey"
    keys: list[str] = Field(min_length=1, max_length=10)

    @field_validator("keys")
    @classmethod
    def keys_must_be_non_empty_and_unique(cls, value: list[str]) -> list[str]:
        """Prevent invalid or ambiguous shortcut definitions."""
        normalized = [key.strip() for key in value]
        if any(not key for key in normalized):
            raise ValueError("hotkey keys must not be blank")
        if len({key.casefold() for key in normalized}) != len(normalized):
            raise ValueError("hotkey keys must be unique")
        return normalized


class ScrollAction(BaseAction):
    """Scroll by signed pixel or platform-unit deltas."""

    type: Literal["scroll"] = "scroll"
    delta_x: int = 0
    delta_y: int
    x: int | None = None
    y: int | None = None

    @model_validator(mode="after")
    def target_coordinates_must_be_complete(self) -> ScrollAction:
        if (self.x is None) != (self.y is None):
            raise ValueError("scroll x and y must be supplied together")
        return self


class DragAction(BaseAction):
    """Drag from one absolute coordinate to another."""

    type: Literal["drag"] = "drag"
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int = Field(default=500, ge=1, le=60_000)
    button: Literal["left", "middle", "right"] = "left"


class WaitAction(BaseAction):
    """Pause runtime progress for a bounded duration."""

    type: Literal["wait"] = "wait"
    duration_ms: int = Field(ge=0, le=300_000)


class ScreenshotAction(BaseAction):
    """Request a new screenshot observation."""

    type: Literal["screenshot"] = "screenshot"
    monitor: int | None = Field(default=None, ge=0)


class OpenAppAction(BaseAction):
    """Open an application by a platform-resolvable name."""

    type: Literal["open_app"] = "open_app"
    application: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)


class WindowAction(BaseAction):
    """Base for actions that identify a window by id or title."""

    window_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value

    def model_post_init(self, __context: Any) -> None:
        if self.window_id is None and self.title is None:
            raise ValueError("either window_id or title is required")


class FocusWindowAction(WindowAction):
    """Bring a matching window to the foreground."""

    type: Literal["focus_window"] = "focus_window"


class CloseWindowAction(WindowAction):
    """Close a matching window."""

    type: Literal["close_window"] = "close_window"


class BrowserNavigateAction(BaseAction):
    """Navigate the active browser context to an HTTP(S) URL."""

    type: Literal["browser_navigate"] = "browser_navigate"
    url: str = Field(pattern=r"^https?://", min_length=8)


class BrowserBackAction(BaseAction):
    """Navigate backward in browser history."""

    type: Literal["browser_back"] = "browser_back"


class BrowserForwardAction(BaseAction):
    """Navigate forward in browser history."""

    type: Literal["browser_forward"] = "browser_forward"


class BrowserReloadAction(BaseAction):
    """Reload the current browser page."""

    type: Literal["browser_reload"] = "browser_reload"
    bypass_cache: bool = False


class FinishAction(BaseAction):
    """Declare that the task has completed successfully."""

    type: Literal["finish"] = "finish"
    message: str | None = Field(default=None, min_length=1)


class FailAction(BaseAction):
    """Declare that the task cannot continue."""

    type: Literal["fail"] = "fail"
    reason: str = Field(min_length=1)
    retryable: bool = False


Action = Annotated[
    ClickAction
    | DoubleClickAction
    | RightClickAction
    | MoveCursorAction
    | TypeAction
    | PasteAction
    | KeyAction
    | HotkeyAction
    | ScrollAction
    | DragAction
    | WaitAction
    | ScreenshotAction
    | OpenAppAction
    | FocusWindowAction
    | CloseWindowAction
    | BrowserNavigateAction
    | BrowserBackAction
    | BrowserForwardAction
    | BrowserReloadAction
    | FinishAction
    | FailAction,
    Field(discriminator="type"),
]

ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action_json(value: str | bytes) -> Action:
    """Deserialize and validate one VAP action from JSON."""
    return ACTION_ADAPTER.validate_json(value)


def dump_action_json(action: Action, *, indent: int | None = None) -> str:
    """Serialize one validated VAP action to JSON."""
    return ACTION_ADAPTER.dump_json(action, indent=indent).decode()


def action_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for the complete VAP action union."""
    return ACTION_ADAPTER.json_schema()
