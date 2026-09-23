import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.errors import violated_constraint
from app.core.enums import AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from tests.support import make_user


async def test_reports_the_violated_constraint_name(session: AsyncSession) -> None:
    await make_user(session, role=UserRole.PM, email="ama@bonarda.works")
    session.add(
        UserAccount(
            email="ama@bonarda.works", role=UserRole.PM, auth_provider=AuthProvider.CORPORATE_SSO
        )
    )

    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()

    assert violated_constraint(excinfo.value) == "uq_user_accounts_email"
