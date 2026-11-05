"""Route browser VAP actions to a CDP session, preferring semantic control."""

from __future__ import annotations

import base64
from time import perf_counter

from vlmux.browser.session import BrowserSession
from vlmux.core import ActionResult, Observation, ScreenObservation
from vlmux.exceptions import ActionExecutionError
from vlmux.protocol import (
    Action,
    BrowserBackAction,
    BrowserForwardAction,
    BrowserNavigateAction,
    BrowserReloadAction,
)


class BrowserExecutor:
    """Execute browser navigation actions through a :class:`BrowserSession`."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    async def execute(self, action: Action) -> ActionResult:
        """Dispatch one browser action and record a structured outcome."""
        started = perf_counter()
        try:
            if isinstance(action, BrowserNavigateAction):
                await self._session.navigate(action.url)
            elif isinstance(action, BrowserBackAction):
                await self._session.back()
            elif isinstance(action, BrowserForwardAction):
                await self._session.forward()
            elif isinstance(action, BrowserReloadAction):
                await self._session.reload(bypass_cache=action.bypass_cache)
            else:
                raise ActionExecutionError(f"action type '{action.type}' is not a browser action")
        except ActionExecutionError as error:
            return ActionResult(
                action_id=action.id,
                success=False,
                duration_ms=(perf_counter() - started) * 1000,
                error=str(error),
            )
        return ActionResult(
            action_id=action.id,
            success=True,
            duration_ms=(perf_counter() - started) * 1000,
        )

    async def observe(self) -> Observation:
        """Return a DOM-mode observation combining page text and elements."""
        dom = await self._session.dom()
        elements = await self._session.interactive_elements()
        url = await self._session.current_url()
        png = await self._session.screenshot_png()
        screen = ScreenObservation(
            width=1,
            height=1,
            image=base64.b64encode(png).decode("ascii")
            if png
            else base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii"),
            image_format="png",
        )
        return Observation(
            screen=screen,
            metadata={"browser_url": url, "interactive_elements": elements},
            dom={"url": url, "html": dom[:200_000], "elements": elements},
        )
