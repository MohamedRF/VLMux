"""Tests for the CDP browser session, executor, and runtime routing."""

from __future__ import annotations

import asyncio
from typing import Any

from vlmux.browser import BrowserExecutor, BrowserSession
from vlmux.protocol import BrowserBackAction, BrowserNavigateAction


class FakeTransport:
    """Record CDP calls and replay canned results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results: dict[str, Any] = {
            "Page.getFrameTree": {"frameTree": {"frame": {"url": "https://example.com/"}}},
            "Runtime.evaluate": {"result": {"value": True}},
        }

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, params or {}))
        return self.results.get(method, {})

    async def aclose(self) -> None:
        return None


def test_browser_session_navigate_uses_cdp() -> None:
    transport = FakeTransport()
    session = BrowserSession(transport)
    asyncio.run(session.navigate("https://example.com"))
    methods = [method for method, _ in transport.calls]
    assert methods == ["Page.enable", "Page.navigate"]


def test_browser_session_click_element_evaluates_script() -> None:
    transport = FakeTransport()
    session = BrowserSession(transport)
    asyncio.run(session.click_element("#submit"))
    assert transport.calls[-1][0] == "Runtime.evaluate"


def test_browser_session_missing_element_raises() -> None:
    transport = FakeTransport()
    transport.results["Runtime.evaluate"] = {"result": {"value": False}}
    session = BrowserSession(transport)
    try:
        asyncio.run(session.click_element("#missing"))
    except Exception as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("expected failure")


def test_browser_session_interactive_elements_parses_list() -> None:
    transport = FakeTransport()
    transport.results["Runtime.evaluate"] = {
        "result": {"value": [{"selector": "#a", "tag": "button", "text": "Go"}]}
    }
    session = BrowserSession(transport)
    elements = asyncio.run(session.interactive_elements())
    assert elements == [{"selector": "#a", "tag": "button", "text": "Go"}]


def test_browser_executor_dispatches_navigate_and_back() -> None:
    transport = FakeTransport()
    executor = BrowserExecutor(BrowserSession(transport))
    result = asyncio.run(executor.execute(BrowserNavigateAction(url="https://example.com")))
    assert result.success is True
    result_back = asyncio.run(executor.execute(BrowserBackAction()))
    assert result_back.success is True
    methods = [method for method, _ in transport.calls]
    assert "Page.navigateToHistoryEntry" in methods


def test_browser_executor_rejects_desktop_action() -> None:
    from vlmux.protocol import ClickAction

    transport = FakeTransport()
    executor = BrowserExecutor(BrowserSession(transport))
    result = asyncio.run(executor.execute(ClickAction(x=1, y=1)))
    assert result.success is False
