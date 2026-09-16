"""Tests for the local runtime event bus."""

import asyncio

from vlmux.events import Event, EventBus


def test_event_bus_supports_sync_async_and_unsubscribe() -> None:
    bus = EventBus()
    received: list[str] = []

    def sync_handler(event: Event) -> None:
        received.append(f"sync:{event.name}")

    async def async_handler(event: Event) -> None:
        received.append(f"async:{event.name}")

    unsubscribe = bus.subscribe(sync_handler)
    bus.subscribe(async_handler)
    asyncio.run(bus.emit("task.started", task_id="task"))
    unsubscribe()
    asyncio.run(bus.emit("task.completed", task_id="task"))

    assert received == [
        "sync:task.started",
        "async:task.started",
        "async:task.completed",
    ]
