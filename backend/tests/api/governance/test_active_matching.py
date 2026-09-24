from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.governance.service import active_matching


async def test_the_seeded_matching_policy_is_active(session: AsyncSession) -> None:
    policy = await active_matching(session)

    assert policy.version == 1
    assert policy.rules.weights.tier == 0.15
    assert policy.rules.first_shot.panel_size == 5
