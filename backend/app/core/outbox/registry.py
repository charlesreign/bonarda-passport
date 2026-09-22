from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


class HandlerRegistry:
    """Maps event types to named handlers. Names are global and stable
    ("roster.refresh_worker") because they form part of the Arq job ID."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._by_event: defaultdict[str, list[str]] = defaultdict(list)

    def register(self, event: type[DomainEvent] | str, name: str, handler: Handler) -> None:
        event_type = event if isinstance(event, str) else event.event_type
        if name in self._handlers:
            raise ValueError(f"handler {name!r} already registered")
        self._handlers[name] = handler
        self._by_event[event_type].append(name)

    def handler_names_for(self, event_type: str) -> list[str]:
        return list(self._by_event.get(event_type, []))

    def get(self, name: str) -> Handler:
        return self._handlers[name]
