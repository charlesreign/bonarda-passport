"""Public interface of the roster module. No other module imports it."""

from app.modules.roster.refresh import rebuild_all

__all__ = ["rebuild_all"]
