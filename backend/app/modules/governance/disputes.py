"""Disputes (FR-1.4, spec §2.2 #8). governance imports no domain module, so
whether a record belongs to the worker is answered by owner lookups that the
composition root injects (app.wiring.dispute_target_owners)."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.outbox.writer import emit_event
from app.core.pagination import decode_cursor, encode_cursor
from app.core.time import utcnow
from app.modules.governance.enums import DisputeStatus, DisputeTargetType
from app.modules.governance.models import REMOVED_TEXT, Dispute
from app.modules.governance.repository import DisputeRepository
from app.modules.governance.schemas import (
    DisputeCreate,
    DisputeFiled,
    DisputePage,
    DisputeRead,
    DisputeResolve,
    DisputeResolved,
)
from app.modules.identity.service import Permission, has_permission

# The worker a record belongs to, or None when there is no such record.
TargetOwner = Callable[[AsyncSession, UUID], Awaitable[UUID | None]]
DisputeTargetOwners = Mapping[DisputeTargetType, TargetOwner]


def _invalid_cursor() -> BadRequest:
    return BadRequest("Invalid cursor", code="invalid_cursor")


def _after(cursor: str) -> tuple[datetime, UUID]:
    values = decode_cursor(cursor, ("due_at", "id"))
    try:
        due_at = datetime.fromisoformat(values["due_at"])
        dispute_id = UUID(values["id"])
    except ValueError as exc:
        raise _invalid_cursor() from exc
    if due_at.tzinfo is None:
        raise _invalid_cursor()
    return due_at, dispute_id


class DisputeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.disputes = DisputeRepository(session)

    async def file(
        self, actor: Actor, data: DisputeCreate, *, owners: DisputeTargetOwners, sla_days: int
    ) -> Dispute:
        if actor.worker_id is None:
            raise Forbidden("This endpoint is for worker accounts", code="not_a_worker")
        # Someone else's record and a missing one answer alike, so the
        # endpoint cannot be used to probe which records exist.
        if await owners[data.target_type](self.session, data.target_id) != actor.worker_id:
            raise NotFound("No such record on your passport", code="dispute_target_not_found")
        try:
            async with self.session.begin_nested():
                dispute = self.disputes.add(
                    Dispute(
                        worker_id=actor.worker_id,
                        target_type=data.target_type,
                        target_id=data.target_id,
                        reason=data.reason,
                        due_at=utcnow() + timedelta(days=sla_days),
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_disputes_open_target":
                raise
            raise Conflict(
                "This record already has an open dispute", code="dispute_already_open"
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="dispute.filed",
            target_type="dispute",
            target_id=dispute.id,
            after={
                "target_type": dispute.target_type.value,
                "target_id": str(dispute.target_id),
                "due_at": dispute.due_at.isoformat(),
            },
        )
        await emit_event(
            self.session,
            DisputeFiled(
                aggregate_id=dispute.id,
                worker_id=dispute.worker_id,
                target_type=dispute.target_type,
                target_id=dispute.target_id,
            ),
        )
        return dispute

    async def list_for(
        self, actor: Actor, *, status: DisputeStatus | None, cursor: str | None, limit: int
    ) -> DisputePage:
        """People Ops see the whole queue; a worker sees their own disputes."""
        if has_permission(actor.role, Permission.DISPUTE_RESOLVE):
            worker_id = None
        elif actor.worker_id is not None:
            worker_id = actor.worker_id
        else:
            raise Forbidden(
                "Only People Ops and workers can list disputes", code="permission_denied"
            )
        rows = await self.disputes.page(
            worker_id=worker_id,
            status=status,
            after=_after(cursor) if cursor is not None else None,
            limit=limit + 1,
        )
        page = rows[:limit]
        next_cursor = (
            encode_cursor({"due_at": page[-1].due_at.isoformat(), "id": str(page[-1].id)})
            if len(rows) > limit
            else None
        )
        return DisputePage(
            items=[DisputeRead.model_validate(d) for d in page], next_cursor=next_cursor
        )

    async def resolve(self, actor: Actor, dispute_id: UUID, data: DisputeResolve) -> Dispute:
        dispute = await self.disputes.get_for_update(dispute_id)
        if dispute is None:
            raise NotFound("Dispute not found", code="dispute_not_found")
        if dispute.status is DisputeStatus.RESOLVED:
            raise Conflict("This dispute is already resolved", code="dispute_already_resolved")
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolution = data.resolution
        dispute.resolution_notes = data.resolution_notes
        dispute.resolver_id = actor.user_id
        dispute.resolved_at = utcnow()
        await write_audit(
            self.session,
            actor=actor,
            action="dispute.resolved",
            target_type="dispute",
            target_id=dispute.id,
            before={"status": DisputeStatus.OPEN.value},
            after={"status": DisputeStatus.RESOLVED.value, "resolution": data.resolution.value},
        )
        await emit_event(
            self.session,
            DisputeResolved(
                aggregate_id=dispute.id,
                worker_id=dispute.worker_id,
                target_type=dispute.target_type,
                target_id=dispute.target_id,
                resolution=data.resolution,
            ),
        )
        return dispute


async def scrub_dispute_text(
    session: AsyncSession, *, worker_id: UUID | None = None, resolved_before: datetime | None = None
) -> int:
    """Replaces dispute reasons and notes, keeping the structure (spec §6.3,
    §6.6): for one worker on erasure, or for disputes resolved before the
    retention cutoff. Returns how many were scrubbed."""
    disputes = await DisputeRepository(session).with_text(
        worker_id=worker_id, resolved_before=resolved_before
    )
    for dispute in disputes:
        dispute.reason = REMOVED_TEXT
        if dispute.resolution_notes is not None:
            dispute.resolution_notes = REMOVED_TEXT
        await write_audit(
            session,
            actor=None,
            action="dispute.text_removed",
            target_type="dispute",
            target_id=dispute.id,
            reason="worker_anonymized" if worker_id is not None else "retention",
        )
    return len(disputes)
