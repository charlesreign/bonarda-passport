from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from alembic.config import Config
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.modules.identity.models import UserAccount
from app.modules.identity.tokens import issue_access_token

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def make_user(
    session: AsyncSession,
    *,
    role: UserRole = UserRole.PM,
    email: str | None = None,
    status: AccountStatus = AccountStatus.ACTIVE,
    oidc_subject: str | None = None,
    worker_id: UUID | None = None,
) -> UserAccount:
    is_worker = role is UserRole.WORKER
    user = UserAccount(
        email=(email or f"{uuid4().hex[:10]}@example.com").strip().lower(),
        role=role,
        auth_provider=AuthProvider.MAGIC_LINK if is_worker else AuthProvider.CORPORATE_SSO,
        status=status,
        oidc_subject=oidc_subject if not is_worker else None,
        worker_id=(worker_id or uuid4()) if is_worker else None,
    )
    session.add(user)
    await session.commit()
    return user


def bearer(settings: Settings, user: UserAccount, *, now: datetime | None = None) -> dict[str, str]:
    token = issue_access_token(
        settings, user_id=user.id, role=user.role, worker_id=user.worker_id, amr=["test"], now=now
    )
    return {"Authorization": f"Bearer {token}"}
