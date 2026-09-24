from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig
from app.modules.identity.models import UserAccount
from tests.support import _seed_policy_rows, make_user


def _tiering_rules() -> dict[str, Any]:
    rules: dict[str, Any] = next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "tiering")
    return rules


async def _draft(session: AsyncSession, author: UserAccount) -> PolicyConfig:
    policy = PolicyConfig(
        kind=PolicyKind.TIERING, version=2, rules=_tiering_rules(), created_by_id=author.id
    )
    session.add(policy)
    await session.commit()
    return policy


_SEED_TIERING = (PolicyConfig.kind == PolicyKind.TIERING) & (PolicyConfig.version == 1)


@pytest.mark.parametrize(
    "values", [{"rules": {"window_months": 1}}, {"notes": "edited"}, {"version": 7}]
)
async def test_a_proposed_policy_cannot_be_edited(
    session: AsyncSession, values: dict[str, Any]
) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    with pytest.raises(DBAPIError, match="a proposed policy is immutable"):
        await session.execute(
            update(PolicyConfig).where(PolicyConfig.id == policy.id).values(**values)
        )
    await session.rollback()


async def test_a_draft_cannot_be_retired_without_going_live(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    with pytest.raises(DBAPIError, match="cannot move from draft to retired"):
        await session.execute(
            update(PolicyConfig)
            .where(PolicyConfig.id == policy.id)
            .values(status=PolicyStatus.RETIRED)
        )
    await session.rollback()


async def test_a_live_policy_cannot_return_to_draft(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="cannot move from active to draft"):
        await session.execute(
            update(PolicyConfig).where(_SEED_TIERING).values(status=PolicyStatus.DRAFT)
        )
    await session.rollback()


async def test_the_activation_stamp_is_fixed_once_live(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="activation is immutable"):
        await session.execute(
            update(PolicyConfig)
            .where(_SEED_TIERING)
            .values(activated_at=utcnow() - timedelta(days=1))
        )
    await session.rollback()


async def test_a_live_policy_needs_an_activation_time(session: AsyncSession) -> None:
    session.add(
        PolicyConfig(kind=PolicyKind.CONCENTRATION, version=1, rules={}, status=PolicyStatus.ACTIVE)
    )

    with pytest.raises(IntegrityError, match="ck_policy_configs_activated_when_live"):
        await session.commit()


async def test_deleting_the_author_still_clears_created_by(session: AsyncSession) -> None:
    ops = await make_user(session, role=UserRole.PEOPLE_OPS)
    policy = await _draft(session, ops)

    await session.execute(delete(UserAccount).where(UserAccount.id == ops.id))
    await session.commit()

    await session.refresh(policy)
    assert policy.created_by_id is None
