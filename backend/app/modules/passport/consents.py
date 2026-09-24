from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.passport.dependencies import WorkerActor
from app.modules.passport.enums import ConsentPurpose
from app.modules.passport.models import Consent
from app.modules.passport.repository import ConsentRepository
from app.modules.passport.schemas import ConsentChanged, ConsentRead

# GDPR Art. 6(1)(a) / Ghana DPA: processing based on the worker's own consent.
LEGAL_BASIS_CONSENT = "consent"


def _read(purpose: ConsentPurpose, consent: Consent | None) -> ConsentRead:
    if consent is None:
        return ConsentRead(
            purpose=purpose, granted=False, legal_basis=None, granted_at=None, withdrawn_at=None
        )
    return ConsentRead(
        purpose=purpose,
        granted=consent.granted,
        legal_basis=consent.legal_basis,
        granted_at=consent.granted_at,
        withdrawn_at=consent.withdrawn_at,
    )


class ConsentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.consents = ConsentRepository(session)

    async def list_for(self, worker_id: UUID) -> list[ConsentRead]:
        existing = {c.purpose: c for c in await self.consents.list_for_worker(worker_id)}
        return [_read(purpose, existing.get(purpose)) for purpose in ConsentPurpose]

    async def set(self, who: WorkerActor, purpose: ConsentPurpose, granted: bool) -> ConsentRead:
        consent = await self.consents.get(who.worker_id, purpose)
        current = consent.granted if consent is not None else False
        if granted == current:
            return _read(purpose, consent)
        now = utcnow()
        if consent is None:
            consent = self.consents.add(
                Consent(
                    worker_id=who.worker_id,
                    purpose=purpose,
                    granted=granted,
                    legal_basis=LEGAL_BASIS_CONSENT,
                )
            )
        consent.granted = granted
        if granted:
            consent.granted_at = now
            consent.withdrawn_at = None
        else:
            consent.withdrawn_at = now
        await write_audit(
            self.session,
            actor=who.actor,
            action="consent.granted" if granted else "consent.withdrawn",
            target_type="worker",
            target_id=who.worker_id,
            before={"purpose": purpose.value, "granted": current},
            after={"purpose": purpose.value, "granted": granted},
        )
        await emit_event(
            self.session,
            ConsentChanged(aggregate_id=who.worker_id, purpose=purpose, granted=granted),
        )
        return _read(purpose, consent)
