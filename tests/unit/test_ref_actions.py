"""Tests for ref-based VAP actions (click_ref, set_value_ref)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vlmux.protocol import (
    ClickRefAction,
    SetValueRefAction,
    action_json_schema,
    parse_action_json,
)


def test_click_ref_roundtrip() -> None:
    action = parse_action_json('{"type":"click_ref","ref":"@a1b2c3:e8"}')

    assert isinstance(action, ClickRefAction)
    assert action.ref == "@a1b2c3:e8"
    assert action.button == "left"
    assert action.clicks == 1


def test_click_ref_rejects_bare_element_token() -> None:
    with pytest.raises(ValidationError):
        parse_action_json('{"type":"click_ref","ref":"@e8"}')


def test_click_ref_rejects_garbage_ref() -> None:
    with pytest.raises(ValidationError):
        parse_action_json('{"type":"click_ref","ref":"button-Save"}')


def test_set_value_ref_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        parse_action_json('{"type":"set_value_ref","ref":"@a1:e1","value":1}')


def test_set_value_ref_accepts_empty_value() -> None:
    action = parse_action_json('{"type":"set_value_ref","ref":"@a1:e1","value":""}')

    assert isinstance(action, SetValueRefAction)
    assert action.value == ""


def test_schema_includes_ref_actions() -> None:
    schema = action_json_schema()
    mapping = schema["discriminator"]["mapping"]

    assert "click_ref" in mapping
    assert "set_value_ref" in mapping
    assert schema["$defs"]["ClickRefAction"]["properties"]["type"]["const"] == "click_ref"
    assert schema["$defs"]["SetValueRefAction"]["properties"]["type"]["const"] == "set_value_ref"
