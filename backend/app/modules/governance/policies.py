from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.db.errors import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound, UnprocessableEntity
from app.core.outbox.writer import emit_event
from app.core.time import utcnow
from app.modules.governance.enums import PolicyKind, PolicyStatus
from app.modules.governance.models import PolicyConfig
from app.modules.governance.repository import PolicyRepository
from app.modules.governance.schemas import (
    RULES_BY_KIND,
    PolicyActivated,
    PolicyCreate,
    PolicyRead,
    TieringPolicy,
    TieringRules,
)


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}" if location else str(error["msg"])


class PolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policies = PolicyRepository(session)

    async def list_versions(self, kind: PolicyKind) -> list[PolicyRead]:
        return [PolicyRead.model_validate(p) for p in await self.policies.list_for_kind(kind)]

    async def propose(self, actor: Actor, kind: PolicyKind, data: PolicyCreate) -> PolicyConfig:
        schema = RULES_BY_KIND.get(kind)
        if schema is None:
            raise BadRequest(
                "Policies of this kind arrive in a later release",
                code="policy_kind_not_supported",
            )
        try:
            rules = schema.model_validate(data.rules)
        except ValidationError as exc:
            raise UnprocessableEntity(_first_error(exc), code="invalid_policy_rules") from exc
        try:
            async with self.session.begin_nested():
                policy = self.policies.add(
                    PolicyConfig(
                        kind=kind,
                        version=await self.policies.next_version(kind),
                        rules=rules.model_dump(mode="json"),
                        notes=data.notes,
                        created_by_id=actor.user_id,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_policy_configs_kind_version":
                raise
            raise Conflict(
                "Another version was proposed at the same time; try again",
                code="policy_version_conflict",
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="policy.proposed",
            target_type="policy",
            target_id=policy.id,
            after={"kind": kind.value, "version": policy.version},
        )
        return policy

    async def activate(self, actor: Actor, kind: PolicyKind, version: int) -> PolicyConfig:
        policy = await self.policies.get_for_update(kind, version)
        if policy is None:
            raise NotFound("Policy version not found", code="policy_not_found")
        if policy.status is not PolicyStatus.DRAFT:
            raise Conflict("Only a draft policy can be activated", code="policy_not_draft")
        if policy.created_by_id == actor.user_id:
            raise Forbidden(
                "A policy must be activated by someone other than its author",
                code="policy_self_activation",
            )
        current = await self.policies.active(kind, for_update=True)
        previous_version = current.version if current is not None else None
        try:
            async with self.session.begin_nested():
                if current is not None:
                    current.status = PolicyStatus.RETIRED
                    await self.session.flush()
                policy.status = PolicyStatus.ACTIVE
                policy.activated_by_id = actor.user_id
                policy.activated_at = utcnow()
                await self.session.flush()
        except IntegrityError as exc:
            if violated_constraint(exc) != "uq_policy_configs_active_kind":
                raise
            raise Conflict(
                "Another version was activated at the same time; reload and try again",
                code="policy_activation_conflict",
            ) from exc
        await write_audit(
            self.session,
            actor=actor,
            action="policy.activated",
            target_type="policy",
            target_id=policy.id,
            before={"active_version": previous_version},
            after={"active_version": policy.version},
        )
        await emit_event(
            self.session,
            PolicyActivated(
                aggregate_id=policy.id,
                kind=kind,
                version=policy.version,
                previous_version=previous_version,
            ),
        )
        return policy


async def active_tiering(session: AsyncSession) -> TieringPolicy:
    policy = await PolicyRepository(session).active(PolicyKind.TIERING)
    if policy is None:
        raise RuntimeError("no active tiering policy; migration 0008 seeds one")
    return TieringPolicy(
        id=policy.id, version=policy.version, rules=TieringRules.model_validate(policy.rules)
    )


async def policy_versions(session: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, int]:
    return await PolicyRepository(session).versions_by_id(ids)
