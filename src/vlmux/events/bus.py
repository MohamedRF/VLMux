"""Small async-compatible event bus for local runtime tracing."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """One immutable runtime event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """Deliver local events in subscription order."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> Callable[[], None]:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    async def emit(self, name: str, **data: Any) -> Event:
        event = Event(name=name, data=data)
        for handler in tuple(self._handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        return event
