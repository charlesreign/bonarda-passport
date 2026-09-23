import enum

import sqlalchemy as sa


def pg_enum(enum_cls: type[enum.Enum]) -> sa.Enum:
    """Native Postgres ENUM that stores member *values* ("people_ops"), not names."""
    return sa.Enum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
