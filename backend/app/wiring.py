"""Composition root: the only place that knows every module's handlers and
visibility sources. Later plans register theirs here."""

from app.core.outbox.registry import HandlerRegistry
from app.modules.identity.service import VisibilitySource


def build_registry() -> HandlerRegistry:
    return HandlerRegistry()


def visibility_sources() -> list[VisibilitySource]:
    return []
