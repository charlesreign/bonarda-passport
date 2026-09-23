from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.events import DomainEvent
from app.core.outbox.registry import HandlerRegistry


class Pinged(DomainEvent):
    event_type: ClassVar[str] = "test.pinged"


async def _noop(session: AsyncSession, payload: dict[str, Any]) -> None:
    return None


def test_registers_handlers_by_event_class_or_name() -> None:
    registry = HandlerRegistry()
    registry.register(Pinged, "a.first", _noop)
    registry.register("test.pinged", "b.second", _noop)

    assert registry.handler_names_for("test.pinged") == ["a.first", "b.second"]
    assert registry.get("a.first") is _noop
    assert registry.handler_names_for("test.unknown") == []


def test_duplicate_handler_name_is_rejected() -> None:
    registry = HandlerRegistry()
    registry.register(Pinged, "a.first", _noop)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(Pinged, "a.first", _noop)
