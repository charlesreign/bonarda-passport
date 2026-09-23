from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.enums import AccountStatus, UserRole
from app.core.errors import BadRequest, NotFound
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.models import AccessGrant
from app.modules.identity.repository import AccessGrantRepository, UserRepository
from app.modules.identity.schemas import GrantCreate, GrantCreated, GrantRead

MAX_GRANT_DURATION = timedelta(days=90)


class GrantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.grants = AccessGrantRepository(session)
        self.users = UserRepository(session)

    async def create(self, actor: Actor, data: GrantCreate) -> AccessGrant:
        now = utcnow()
        if data.expires_at <= now:
            raise BadRequest("Expiry must be in the future", code="grant_expiry_in_past")
        if data.expires_at > now + MAX_GRANT_DURATION:
            raise BadRequest("Grants may last at most 90 days", code="grant_too_long")
        grantee = await self.users.get(data.granted_to_id)
        if (
            grantee is None
            or grantee.role is not UserRole.PM
            or grantee.status is not AccountStatus.ACTIVE
        ):
            raise BadRequest("Grants can only be given to active PMs", code="grant_invalid_grantee")
        # identity does not import passport: the FK to workers is the check.
        # A savepoint keeps the outer transaction usable if it fails.
        try:
            async with self.session.begin_nested():
                grant = self.grants.add(
                    AccessGrant(
                        granted_to_id=data.granted_to_id,
                        scoped_worker_id=data.scoped_worker_id,
                        granted_by_id=actor.user_id,
                        reason=data.reason,
                        expires_at=data.expires_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "fk_access_grants_scoped_worker_id":
                raise
            raise BadRequest("No worker with this id", code="grant_worker_not_found") from exc
        await write_audit(
            self.session,
            actor=actor,
            action="access_grant.created",
            target_type="access_grant",
            target_id=grant.id,
            after=GrantRead.model_validate(grant).model_dump(mode="json"),
            reason=data.reason,
        )
        await emit_event(
            self.session,
            GrantCreated(
                aggregate_id=grant.id,
                granted_to_id=grant.granted_to_id,
                scoped_worker_id=grant.scoped_worker_id,
                expires_at=grant.expires_at,
            ),
        )
        return grant

    async def revoke(self, actor: Actor, grant_id: UUID) -> None:
        grant = await self.grants.get(grant_id)
        if grant is None:
            raise NotFound("Access grant not found", code="grant_not_found")
        if grant.revoked_at is not None:
            return
        grant.revoked_at = utcnow()
        await write_audit(
            self.session,
            actor=actor,
            action="access_grant.revoked",
            target_type="access_grant",
            target_id=grant.id,
            before={"revoked_at": None},
            after={"revoked_at": grant.revoked_at.isoformat()},
        )

    async def list_active(self, granted_to_id: UUID | None) -> list[AccessGrant]:
        return await self.grants.list_active(granted_to_id=granted_to_id, at=utcnow())

    async def sweep_expired(self) -> int:
        """Records each lapsed grant once. Access already stopped at expires_at;
        this only makes the lapse visible in the audit trail (NFR-3.8)."""
        lapsed = await self.grants.list_lapsed(utcnow())
        for grant in lapsed:
            grant.revoked_at = grant.expires_at
            await write_audit(
                self.session,
                actor=None,
                action="access_grant.expired",
                target_type="access_grant",
                target_id=grant.id,
                before={"revoked_at": None},
                after={"revoked_at": grant.expires_at.isoformat()},
            )
        return len(lapsed)
