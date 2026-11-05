"""Browser control via Chrome DevTools Protocol."""

from vlmux.browser.executor import BrowserExecutor
from vlmux.browser.session import BrowserSession, CDPTransport, WebSocketCDPTransport
from vlmux.browser.som import DomElementDetector

__all__ = [
    "BrowserExecutor",
    "BrowserSession",
    "CDPTransport",
    "DomElementDetector",
    "WebSocketCDPTransport",
]
