"""Browser automation over Chrome DevTools Protocol.

The session surface is deliberately small: navigate, semantic element
actions (DOM first, pixel fallback), DOM inspection, and screenshots. The
transport is injected so tests never need a real browser.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from vlmux.exceptions import ActionExecutionError


class CDPTransport(Protocol):
    """Send one CDP command and return its result object."""

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Invoke a CDP method and return the ``result`` payload."""
        ...

    async def aclose(self) -> None:
        """Release transport resources."""
        ...


class WebSocketCDPTransport:
    """CDP transport over a single ``websockets`` connection."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._socket: Any = None
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def _connect(self) -> Any:
        if self._socket is None:
            import websockets

            self._socket = await websockets.connect(self._url, max_size=64 * 1024 * 1024)
        return self._socket

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        async with self._lock:
            socket = await self._connect()
            self._next_id += 1
            request_id = self._next_id
            await socket.send(
                json.dumps({"id": request_id, "method": method, "params": params or {}})
            )
            while True:
                message = json.loads(await socket.recv())
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise ActionExecutionError(f"CDP {method} failed: {message['error']}")
                return message.get("result", {})

    async def aclose(self) -> None:
        """Close the websocket connection if open."""
        if self._socket is not None:
            await self._socket.close()
            self._socket = None


class BrowserSession:
    """High-level browser control backed by an injected CDP transport."""

    def __init__(self, transport: CDPTransport) -> None:
        self._transport = transport

    @property
    def transport(self) -> CDPTransport:
        """Return the underlying transport."""
        return self._transport

    async def navigate(self, url: str) -> None:
        """Navigate the current target to a URL."""
        await self._transport.call("Page.enable")
        await self._transport.call("Page.navigate", {"url": url})

    async def back(self) -> None:
        """Navigate backward in history."""
        await self._transport.call("Page.navigateToHistoryEntry", {"entryIndex": 0})

    async def forward(self) -> None:
        """Navigate forward in history."""
        await self._transport.call("Page.navigateToHistoryEntry", {"entryIndex": 0})

    async def reload(self, *, bypass_cache: bool = False) -> None:
        """Reload the current page, optionally bypassing the cache."""
        await self._transport.call("Page.reload", {"ignoreCache": bypass_cache})

    async def current_url(self) -> str:
        """Return the latest known document URL from the frame tree."""
        tree = await self._transport.call("Page.getFrameTree")
        frame = (tree or {}).get("frameTree", {}).get("frame", {})
        url = frame.get("url", "")
        return url if isinstance(url, str) else ""

    async def page_title(self) -> str:
        """Return the current document title."""
        result = await self._evaluate("document.title")
        return result if isinstance(result, str) else ""

    async def dom(self) -> str:
        """Return the serialized outer HTML of the document."""
        result = await self._evaluate("document.documentElement.outerHTML")
        return result if isinstance(result, str) else ""

    async def interactive_elements(self, *, limit: int = 128) -> list[dict[str, Any]]:
        """List visible interactive elements with selector, role, and bounds."""
        script = """(() => {
          const selectorFor = (el) => {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && parts.length < 4) {
              let part = node.tagName.toLowerCase();
              if (node.parentElement) {
                const siblings = [...node.parentElement.children]
                  .filter(c => c.tagName === node.tagName);
                if (siblings.length > 1) {
                  part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
                }
              }
              parts.unshift(part);
              node = node.parentElement;
            }
            return parts.join(' > ');
          };
          const interactive = 'a,button,input,select,textarea,[role="button"],[tabindex]';
          const els = [...document.querySelectorAll(interactive)]
            .filter(el => el.offsetParent !== null || el === document.activeElement)
            .slice(0, {limit});
          return els.map(el => {
            const r = el.getBoundingClientRect();
            return {
              selector: selectorFor(el),
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              text: (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 120),
              x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              width: Math.round(r.width), height: Math.round(r.height)
            };
          });
        })()""".replace("{limit}", str(limit))
        result = await self._evaluate(script)
        return result if isinstance(result, list) else []

    async def click_element(self, selector: str) -> None:
        """Click an element by selector, scrolling it into view first."""
        script = """(() => {
          const el = document.querySelector({selector});
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return false;
          el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
          el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          return true;
        })()""".replace("{selector}", json.dumps(selector))
        if await self._evaluate(script) is not True:
            raise ActionExecutionError(f"browser element not found or not visible: {selector}")

    async def type_into_element(self, selector: str, text: str) -> None:
        """Focus an element and replace its text content."""
        script = """(() => {
          const el = document.querySelector({selector});
          if (!el) return false;
          el.focus();
          if ('value' in el) {{ el.value = {value}; }}
          else {{ el.textContent = {value}; }}
          el.dispatchEvent(new InputEvent('input', {bubbles: true}));
          return true;
        })()""".replace("{selector}", json.dumps(selector)).replace("{value}", json.dumps(text))
        if await self._evaluate(script) is not True:
            raise ActionExecutionError(f"browser element not found: {selector}")

    async def scroll(self, delta_y: int) -> None:
        """Scroll the page vertically."""
        await self._evaluate(f"window.scrollBy(0, {delta_y})")

    async def screenshot_png(self) -> bytes:
        """Capture the current page as PNG bytes."""
        result = await self._transport.call("Page.captureScreenshot", {"format": "png"})
        import base64

        data = (result or {}).get("data", "")
        return base64.b64decode(data) if data else b""

    async def _evaluate(self, expression: str) -> Any:
        await self._transport.call("Runtime.enable")
        result = await self._transport.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = (result or {}).get("result", {}).get("value")
        return value

    async def aclose(self) -> None:
        """Release the underlying transport."""
        await self._transport.aclose()


async def iter_events(transport: Any) -> AsyncIterator[dict[str, Any]]:
    """Yield lifecycle events if the transport exposes a subscription API."""
    if not hasattr(transport, "events"):
        return
    async for event in transport.events():
        yield event
