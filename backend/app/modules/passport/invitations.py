from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.models import AuditLog
from app.core.audit.writer import write_audit
from app.core.config import Settings
from app.core.context import Actor
from app.core.errors import BadRequest, TooManyRequests
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.identity.service import (
    find_worker_account,
    provision_worker_account,
    request_sign_in_link,
)
from app.modules.passport.enums import OnboardingState, WorkerStatus
from app.modules.passport.models import Worker
from app.modules.passport.repository import WorkerRepository
from app.modules.passport.schemas import InvitationCreate, InvitationRead, WorkerInvited

INVITATION_RESENDS_PER_HOUR = 3


class InvitationService:
    """Standard onboarding path for first-time workers (FR-5.1): the PM creates
    the passport and account; the worker completes the profile themselves."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.workers = WorkerRepository(session)

    async def invite(self, actor: Actor, data: InvitationCreate) -> InvitationRead:
        if data.data_region not in self.settings.data_regions:
            raise BadRequest("Unknown data region", code="unknown_data_region")
        email = data.email.strip().lower()
        resent = await self._resend_if_still_invited(actor, email, data)
        if resent is not None:
            return resent
        worker = self.workers.add(
            Worker(
                full_name=data.full_name.strip(),
                worker_type=data.worker_type,
                data_region=data.data_region,
                status=WorkerStatus.DORMANT,
                onboarding_state=OnboardingState.INVITED,
            )
        )
        await self.session.flush()
        # Raises 409 email_in_use; the request's rollback then removes the worker row.
        user_id = await provision_worker_account(
            self.session, actor=actor, email=email, worker_id=worker.id, locale=data.locale
        )
        # Audit rows about workers carry no contact data (spec §6.3 erasure);
        # target_id identifies the record.
        await write_audit(
            self.session,
            actor=actor,
            action="worker.invited",
            target_type="worker",
            target_id=worker.id,
            after={"data_region": worker.data_region},
        )
        await emit_event(
            self.session, WorkerInvited(aggregate_id=worker.id, invited_by_id=actor.user_id)
        )
        await request_sign_in_link(self.session, user_id, purpose="invitation")
        return InvitationRead(
            worker_id=worker.id, email=email, onboarding_state=worker.onboarding_state
        )

    async def _resend_if_still_invited(
        self, actor: Actor, email: str, data: InvitationCreate
    ) -> InvitationRead | None:
        """A lost invitation email (SMTP outage, dead-lettered mail job) leaves
        a worker stuck at `invited` with no way back in. Re-inviting a worker
        still in that state resends the sign-in link instead of failing with
        409 email_in_use; any other existing account still hits that path."""
        ref = await find_worker_account(self.session, email)
        if ref is None:
            return None
        worker = await self.workers.get(ref.worker_id)
        if worker is None or worker.onboarding_state is not OnboardingState.INVITED:
            return None
        since = utcnow() - timedelta(hours=1)
        recent = await self.session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "worker.invitation_resent",
                AuditLog.target_id == worker.id,
                AuditLog.occurred_at >= since,
            )
        )
        if (recent or 0) >= INVITATION_RESENDS_PER_HOUR:
            raise TooManyRequests(
                "This invitation was resent too often; try again later",
                code="invitation_resend_limited",
            )
        before = {
            "full_name": worker.full_name,
            "data_region": worker.data_region,
            "worker_type": worker.worker_type.value,
        }
        worker.full_name = data.full_name.strip()
        worker.data_region = data.data_region
        worker.worker_type = data.worker_type
        after = {
            "full_name": worker.full_name,
            "data_region": worker.data_region,
            "worker_type": worker.worker_type.value,
        }
        await write_audit(
            self.session,
            actor=actor,
            action="worker.invitation_resent",
            target_type="worker",
            target_id=worker.id,
            before=before,
            after=after,
        )
        await request_sign_in_link(self.session, ref.user_id, purpose="invitation")
        return InvitationRead(
            worker_id=worker.id,
            email=email,
            onboarding_state=worker.onboarding_state,
            resent=True,
        )
