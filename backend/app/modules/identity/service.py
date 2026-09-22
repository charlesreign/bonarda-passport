"""Public interface of the identity module. Other modules import from here
(and from schemas) only — never from identity's internal files."""

from app.modules.identity.dependencies import CurrentActor

__all__ = ["CurrentActor"]
