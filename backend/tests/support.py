import importlib.util
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from alembic.config import Config
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.outbox.models import OutboxEvent
from app.core.outbox.processing import process_event
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementPath, EngagementStatus, WorkMode
from app.modules.engagements.models import Engagement, Feedback, Project, ProjectStaff
from app.modules.governance.enums import DisputeResolution, DisputeStatus, DisputeTargetType
from app.modules.governance.models import Dispute, PolicyConfig
from app.modules.identity.models import UserAccount
from app.modules.identity.tokens import issue_access_token
from app.modules.integrations.service import sign_payload
from app.modules.passport.enums import OnboardingState, WorkerStatus, WorkerType
from app.modules.passport.models import Skill, SkillClaim, Worker
from app.modules.roster.service import rebuild_all

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
    locale: str = "en",
) -> UserAccount:
    is_worker = role is UserRole.WORKER
    if is_worker and worker_id is None:
        worker = Worker(
            full_name="Test Worker", worker_type=WorkerType.FREELANCER, data_region="GH"
        )
        session.add(worker)
        await session.flush()
        worker_id = worker.id
    user = UserAccount(
        email=(email or f"{uuid4().hex[:10]}@example.com").strip().lower(),
        role=role,
        auth_provider=AuthProvider.MAGIC_LINK if is_worker else AuthProvider.CORPORATE_SSO,
        status=status,
        oidc_subject=oidc_subject if not is_worker else None,
        worker_id=worker_id if is_worker else None,
        locale=locale,
    )
    session.add(user)
    await session.commit()
    return user


async def make_worker(
    session: AsyncSession,
    *,
    email: str | None = None,
    full_name: str = "Kofi Mensah",
    data_region: str = "GH",
    status: WorkerStatus = WorkerStatus.DORMANT,
    onboarding_state: OnboardingState = OnboardingState.PROFILE_COMPLETE,
    locale: str = "en",
) -> tuple[Worker, UserAccount]:
    worker = Worker(
        full_name=full_name,
        worker_type=WorkerType.FREELANCER,
        data_region=data_region,
        status=status,
        onboarding_state=onboarding_state,
    )
    session.add(worker)
    await session.flush()
    user = await make_user(
        session, role=UserRole.WORKER, email=email, worker_id=worker.id, locale=locale
    )
    return worker, user


def bearer(settings: Settings, user: UserAccount, *, now: datetime | None = None) -> dict[str, str]:
    token = issue_access_token(
        settings, user_id=user.id, role=user.role, worker_id=user.worker_id, amr=["test"], now=now
    )
    return {"Authorization": f"Bearer {token}"}


@dataclass
class RecordingMailer:
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

    def token(self) -> str:
        match = re.search(r"token=([A-Za-z0-9_-]+)", self.sent[-1]["body"])
        assert match is not None
        return match.group(1)


async def make_project(
    session: AsyncSession,
    *,
    staff: list[UserAccount] | None = None,
    data_region: str = "GH",
    name: str = "Project Volta",
    required_skill_ids: list[UUID] | None = None,
    starts_on: date | None = None,
) -> Project:
    project = Project(
        name=name,
        data_region=data_region,
        required_skill_ids=required_skill_ids or [],
        starts_on=starts_on,
    )
    session.add(project)
    await session.flush()
    for user in staff or []:
        session.add(
            ProjectStaff(project_id=project.id, user_account_id=user.id, active_from=utcnow())
        )
    await session.commit()
    return project


async def make_ready_worker(
    session: AsyncSession,
    *,
    email: str | None = None,
    data_region: str = "GH",
    full_name: str = "Kofi Mensah",
) -> tuple[Worker, UserAccount]:
    """A worker who can be engaged: onboarding complete, location, a language
    and one skill claim (data-analysis)."""
    worker, account = await make_worker(
        session, email=email, data_region=data_region, full_name=full_name
    )
    worker.base_location = "Accra"
    worker.languages = ["en"]
    skill = await session.scalar(select(Skill).where(Skill.slug == "data-analysis"))
    if skill is None:
        skill = Skill(slug="data-analysis", name_i18n={"en": "Data analysis"})
        session.add(skill)
        await session.flush()
    session.add(SkillClaim(worker_id=worker.id, skill_id=skill.id))
    await session.commit()
    return worker, account


async def make_engagement(
    session: AsyncSession,
    *,
    worker_id: UUID,
    project_id: UUID,
    status: EngagementStatus = EngagementStatus.COMPLETED,
    path: EngagementPath = EngagementPath.FIRST_TIME,
    start_date: date = date(2026, 1, 5),
    end_date: date | None = None,
    rate: Decimal = Decimal("450.00"),
    currency: str = "GHS",
    work_mode: WorkMode = WorkMode.REMOTE,
    scope: str = "Build the data pipeline",
    completed_at: datetime | None = None,
) -> Engagement:
    engagement = Engagement(
        worker_id=worker_id,
        project_id=project_id,
        path=path,
        status=status,
        start_date=start_date,
        end_date=end_date,
        rate=rate,
        currency=currency,
        work_mode=work_mode,
        contract_terms={"scope": scope, "access_notes": None},
        confirmed_at=utcnow(),
        completed_at=completed_at or (utcnow() if status is EngagementStatus.COMPLETED else None),
    )
    session.add(engagement)
    await session.commit()
    return engagement


def engagement_terms(project_id: UUID, **overrides: object) -> dict[str, object]:
    terms: dict[str, object] = {
        "project_id": str(project_id),
        "start_date": utcnow().date().isoformat(),
        "rate": "450.00",
        "currency": "GHS",
        "work_mode": "remote",
        "location": None,
        "contract_terms": {"scope": "Build the data pipeline", "access_notes": "VPN and repo"},
    }
    terms.update(overrides)
    return terms


async def drain_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: HandlerRegistry,
    *,
    max_rounds: int = 10,
) -> None:
    """Test stand-in for the relay + Arq worker: runs every pending event's
    handlers in-process (including events those handlers emit) until the
    outbox is empty. Handler exceptions propagate to the test."""
    for _ in range(max_rounds):
        async with sessionmaker() as s:
            events = (
                await s.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.dispatched_at.is_(None))
                    .order_by(OutboxEvent.id)
                )
            ).all()
        if not events:
            return
        for event in events:
            for name in registry.handler_names_for(event.event_type):
                await process_event(sessionmaker, registry, event.event_id, name)
            async with sessionmaker() as s, s.begin():
                await s.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == event.id)
                    .values(dispatched_at=utcnow())
                )
    raise AssertionError("outbox did not drain")


def _seed_policy_rows() -> list[dict[str, Any]]:
    """The seed policies exactly as migration 0008 inserts them."""
    path = BACKEND_DIR / "alembic" / "versions" / "0008_policies.py"
    spec = importlib.util.spec_from_file_location("bonarda_migration_0008", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeds: list[dict[str, Any]] = module.SEED_POLICIES
    return seeds


async def seed_policies(conn: AsyncConnection) -> None:
    """Re-inserts the active seed policies after a test's TRUNCATE."""
    now = utcnow()
    await conn.execute(
        PolicyConfig.__table__.insert(),
        [{**seed, "status": "active", "activated_at": now} for seed in _seed_policy_rows()],
    )


def esign_webhook(settings: Settings, payload: dict[str, object]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    timestamp = int(utcnow().timestamp())
    secret = settings.esign_webhook_secret.get_secret_value()
    return body, {
        "Content-Type": "application/json",
        "X-Bonarda-Timestamp": str(timestamp),
        "X-Bonarda-Signature": sign_payload(secret, timestamp, body),
    }


POSITIVE_ANSWERS = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": True,
    "would_reengage": True,
}


async def refresh_roster(session: AsyncSession) -> None:
    """Rebuilds every roster row, as the nightly job does. rebuild_all
    commits per batch itself, so no commit is needed here."""
    await rebuild_all(session)


async def make_feedback(
    session: AsyncSession,
    *,
    engagement_id: UUID,
    reviewer_id: UUID | None,
    answers: dict[str, bool] | None = None,
    skill_ids: list[UUID] | None = None,
    excluded: bool = False,
) -> Feedback:
    feedback = Feedback(
        engagement_id=engagement_id,
        reviewer_id=reviewer_id,
        structured_answers=dict(answers or POSITIVE_ANSWERS),
        skill_ids_demonstrated=skill_ids or [],
        excluded_from_standing=excluded,
    )
    session.add(feedback)
    await session.commit()
    return feedback


async def make_dispute(
    session: AsyncSession,
    *,
    worker_id: UUID,
    due_at: datetime,
    target_type: DisputeTargetType = DisputeTargetType.ENGAGEMENT,
    target_id: UUID | None = None,
    resolved: bool = False,
) -> Dispute:
    dispute = Dispute(
        worker_id=worker_id,
        target_type=target_type,
        target_id=target_id or uuid4(),
        reason="Seeded dispute reason",
        due_at=due_at,
    )
    if resolved:
        dispute.status = DisputeStatus.RESOLVED
        dispute.resolution = DisputeResolution.REJECTED
        dispute.resolution_notes = "Seeded resolution notes"
        dispute.resolved_at = utcnow() - timedelta(days=1)
    session.add(dispute)
    await session.commit()
    return dispute
