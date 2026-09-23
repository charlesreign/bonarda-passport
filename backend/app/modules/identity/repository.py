from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import AccessGrant, RefreshSession, UserAccount


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID) -> UserAccount | None:
        return await self.session.get(UserAccount, user_id)

    async def get_by_email(self, email: str) -> UserAccount | None:
        return await self.session.scalar(
            select(UserAccount).where(UserAccount.email == normalize_email(email))
        )

    async def get_by_oidc_subject(self, subject: str) -> UserAccount | None:
        return await self.session.scalar(
            select(UserAccount).where(UserAccount.oidc_subject == subject)
        )

    def add(self, user: UserAccount) -> UserAccount:
        user.email = normalize_email(user.email)
        self.session.add(user)
        return user


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hash(self, token_hash: str) -> RefreshSession | None:
        return await self.session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        """Locks the row so a concurrent rotation of the same token blocks until
        this transaction commits, instead of both requests reading it valid."""
        return await self.session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash).with_for_update()
        )

    def add(self, row: RefreshSession) -> RefreshSession:
        self.session.add(row)
        return row

    async def revoke_family(self, family_id: UUID, at: datetime, *, reason: str) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=at, revoked_reason=reason)
        )

    async def revoke_all_for_user(self, user_id: UUID, at: datetime, *, reason: str) -> None:
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=at, revoked_reason=reason)
        )


class AccessGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, grant_id: UUID) -> AccessGrant | None:
        return await self.session.get(AccessGrant, grant_id)

    def add(self, grant: AccessGrant) -> AccessGrant:
        self.session.add(grant)
        return grant

    async def has_active(self, granted_to_id: UUID, worker_id: UUID, at: datetime) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        AccessGrant.granted_to_id == granted_to_id,
                        AccessGrant.scoped_worker_id == worker_id,
                        AccessGrant.revoked_at.is_(None),
                        AccessGrant.expires_at > at,
                    )
                )
            )
        )

    async def list_active(self, *, granted_to_id: UUID | None, at: datetime) -> list[AccessGrant]:
        stmt = select(AccessGrant).where(
            AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > at
        )
        if granted_to_id is not None:
            stmt = stmt.where(AccessGrant.granted_to_id == granted_to_id)
        return list((await self.session.scalars(stmt.order_by(AccessGrant.expires_at))).all())

    async def list_open_for_grantee(self, granted_to_id: UUID) -> list[AccessGrant]:
        return list(
            (
                await self.session.scalars(
                    select(AccessGrant).where(
                        AccessGrant.granted_to_id == granted_to_id,
                        AccessGrant.revoked_at.is_(None),
                    )
                )
            ).all()
        )

    async def list_lapsed(self, at: datetime) -> list[AccessGrant]:
        return list(
            (
                await self.session.scalars(
                    select(AccessGrant).where(
                        AccessGrant.revoked_at.is_(None), AccessGrant.expires_at <= at
                    )
                )
            ).all()
        )
