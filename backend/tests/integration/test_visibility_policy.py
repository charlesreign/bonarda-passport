from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.identity.models import AccessGrant
from app.modules.identity.visibility import Visibility, VisibilityPolicy
from tests.support import make_user


def _actor(role: UserRole, worker_id: UUID | None = None) -> Actor:
    return Actor(user_id=uuid4(), role=role, worker_id=worker_id)


async def test_worker_sees_only_themselves(session: AsyncSession) -> None:
    me, other = uuid4(), uuid4()
    policy = VisibilityPolicy()

    assert await policy.level(session, _actor(UserRole.WORKER, me), me) is Visibility.SELF
    assert await policy.level(session, _actor(UserRole.WORKER, me), other) is Visibility.NONE


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.PEOPLE_OPS, Visibility.DETAIL),
        (UserRole.ADMIN, Visibility.DETAIL),
        (UserRole.FINANCE, Visibility.NONE),
        (UserRole.PM, Visibility.NONE),
    ],
)
async def test_staff_defaults(session: AsyncSession, role: UserRole, expected: Visibility) -> None:
    assert await VisibilityPolicy().level(session, _actor(role), uuid4()) is expected


async def test_pm_takes_the_highest_level_from_sources(session: AsyncSession) -> None:
    async def summary(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.SUMMARY

    async def none(s: AsyncSession, a: Actor, w: UUID) -> Visibility:
        return Visibility.NONE

    policy = VisibilityPolicy([none, summary])

    assert await policy.level(session, _actor(UserRole.PM), uuid4()) is Visibility.SUMMARY


async def _grant(session: AsyncSession, pm_id: UUID, worker_id: UUID, **overrides: object) -> None:
    values: dict[str, object] = {
        "granted_to_id": pm_id,
        "scoped_worker_id": worker_id,
        "reason": "covering Project Volta staffing",
        "expires_at": utcnow() + timedelta(days=1),
    }
    values.update(overrides)
    session.add(AccessGrant(**values))
    await session.commit()


async def test_active_grant_gives_pm_detail(session: AsyncSession) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker_id = uuid4()
    await _grant(session, pm.id, worker_id)

    level = await VisibilityPolicy().level(session, Actor(pm.id, UserRole.PM), worker_id)

    assert level is Visibility.DETAIL


@pytest.mark.parametrize(
    "overrides",
    [
        {"expires_at": utcnow() - timedelta(seconds=1)},
        {"revoked_at": utcnow() - timedelta(minutes=1)},
    ],
)
async def test_expired_or_revoked_grant_gives_nothing(
    session: AsyncSession, overrides: dict[str, object]
) -> None:
    pm = await make_user(session, role=UserRole.PM)
    worker_id = uuid4()
    await _grant(session, pm.id, worker_id, **overrides)

    level = await VisibilityPolicy().level(session, Actor(pm.id, UserRole.PM), worker_id)

    assert level is Visibility.NONE
