from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import ConsentPurpose
from app.modules.passport.models import Consent, Skill, SkillClaim
from tests.support import make_worker


async def test_a_worker_account_must_point_at_a_real_worker(session: AsyncSession) -> None:
    session.add(
        UserAccount(
            email="ghost@example.com",
            role=UserRole.WORKER,
            auth_provider=AuthProvider.MAGIC_LINK,
            worker_id=uuid4(),
        )
    )

    with pytest.raises(IntegrityError, match="fk_user_accounts_worker_id"):
        await session.commit()


async def test_a_worker_claims_each_skill_once(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
    session.add(skill)
    await session.flush()
    session.add_all([SkillClaim(worker_id=worker.id, skill_id=skill.id) for _ in range(2)])

    with pytest.raises(IntegrityError, match="uq_skill_claims_worker_skill"):
        await session.commit()


async def test_one_consent_row_per_purpose(session: AsyncSession) -> None:
    worker, _ = await make_worker(session)
    session.add_all(
        [
            Consent(
                worker_id=worker.id,
                purpose=ConsentPurpose.CROSS_REGION_MATCHING,
                granted=True,
                legal_basis="consent",
            )
            for _ in range(2)
        ]
    )

    with pytest.raises(IntegrityError, match="uq_consents_worker_purpose"):
        await session.commit()
