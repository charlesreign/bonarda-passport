"""Composition root: the only place that knows every module's handlers.
Later plans register their event handlers here."""

from app.core.outbox.registry import HandlerRegistry


def build_registry() -> HandlerRegistry:
    return HandlerRegistry()
