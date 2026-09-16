"""Tests for VAP action parsing, validation, and serialization."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from vlmux.protocol import (
    Action,
    BrowserBackAction,
    BrowserForwardAction,
    BrowserNavigateAction,
    BrowserReloadAction,
    ClickAction,
    CloseWindowAction,
    DoubleClickAction,
    DragAction,
    FailAction,
    FinishAction,
    FocusWindowAction,
    HotkeyAction,
    KeyAction,
    MoveCursorAction,
    OpenAppAction,
    PasteAction,
    RightClickAction,
    ScreenshotAction,
    ScrollAction,
    TypeAction,
    WaitAction,
    action_json_schema,
    dump_action_json,
    parse_action_json,
)


@pytest.mark.parametrize(
    "action",
    [
        ClickAction(x=1, y=2),
        DoubleClickAction(x=1, y=2),
        RightClickAction(x=1, y=2),
        MoveCursorAction(x=1, y=2),
        TypeAction(text="hello"),
        PasteAction(text="hello"),
        KeyAction(key="enter"),
        HotkeyAction(keys=["ctrl", "s"]),
        ScrollAction(delta_y=-500),
        DragAction(start_x=1, start_y=2, end_x=3, end_y=4),
        WaitAction(duration_ms=100),
        ScreenshotAction(),
        OpenAppAction(application="Calculator"),
        FocusWindowAction(title="Calculator"),
        CloseWindowAction(window_id="window-1"),
        BrowserNavigateAction(url="https://example.com"),
        BrowserBackAction(),
        BrowserForwardAction(),
        BrowserReloadAction(),
        FinishAction(message="done"),
        FailAction(reason="blocked"),
    ],
)
def test_every_action_round_trips_through_discriminated_union(action: Action) -> None:
    encoded = dump_action_json(action)
    decoded = parse_action_json(encoded)

    assert decoded == action
    assert decoded.version == "1.0"
    assert decoded.timestamp.tzinfo is not None


def test_parser_rejects_unknown_action_type() -> None:
    with pytest.raises(ValidationError):
        parse_action_json('{"type":"launch_missiles","version":"1.0"}')


def test_parser_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_action_json('{"type":"click","x":1,"y":2,"unexpected":true}')


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"type":"hotkey","keys":[]}', "too_short"),
        ('{"type":"hotkey","keys":["ctrl","CTRL"]}', "unique"),
        ('{"type":"wait","duration_ms":300001}', "less_than_equal"),
        ('{"type":"focus_window"}', "either window_id or title"),
        ('{"type":"browser_navigate","url":"file:///secret"}', "string_pattern_mismatch"),
    ],
)
def test_parser_rejects_malformed_values(payload: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_action_json(payload)


def test_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ClickAction(x=1, y=2, timestamp=datetime(2026, 1, 1))


def test_absolute_coordinates_allow_negative_virtual_desktop_positions() -> None:
    action = parse_action_json('{"type":"click","x":-100,"y":20}')

    assert isinstance(action, ClickAction)
    assert action.x == -100


def test_action_schema_has_type_discriminator() -> None:
    schema = action_json_schema()

    assert schema["discriminator"]["propertyName"] == "type"
    assert len(schema["oneOf"]) == 21
