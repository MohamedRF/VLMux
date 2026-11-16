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


def test_raising_subscriber_does_not_break_other_handlers() -> None:
    bus = EventBus()
    received: list[str] = []

    def bad_handler(event: Event) -> None:
        raise RuntimeError("boom")

    async def good_handler(event: Event) -> None:
        received.append(event.name)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)
    event = asyncio.run(bus.emit("task.started", task_id="task"))

    assert event.name == "task.started"
    assert received == ["task.started"]


def test_raising_async_subscriber_is_isolated() -> None:
    bus = EventBus()
    received: list[str] = []

    async def bad_handler(event: Event) -> None:
        raise ValueError("boom")

    async def good_handler(event: Event) -> None:
        received.append(event.name)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)
    asyncio.run(bus.emit("model.responded", step=1))

    assert received == ["model.responded"]
