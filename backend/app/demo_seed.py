"""Seeds a demo dataset: staff, workers with history, live projects and one
open dispute. Idempotent: does nothing once the demo People Ops account exists.

Run from backend/: `python -m app.demo_seed`."""

import asyncio
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import models_registry as _models_registry  # noqa: F401 (map every table)
from app.core.config import get_settings
from app.core.context import Actor
from app.core.db.session import create_engine
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.logging import configure_logging
from app.core.time import utcnow
from app.modules.engagements.enums import EngagementPath, EngagementStatus, WorkMode
from app.modules.engagements.models import Engagement, Feedback, Project, ProjectStaff
from app.modules.governance.enums import DisputeTargetType, PolicyKind
from app.modules.governance.models import Dispute
from app.modules.governance.policies import PolicyService, active_matching
from app.modules.governance.schemas import PolicyCreate
from app.modules.identity.models import UserAccount
from app.modules.passport.enums import (
    AvailabilityStatus,
    ConsentPurpose,
    OnboardingState,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)
from app.modules.passport.models import Consent, Skill, SkillClaim, Worker
from app.modules.roster.service import rebuild_all
from app.modules.standing.service import recalculate_all_standing
from app.nightly import run_concentration_rollup

log = structlog.get_logger(__name__)

OPS_EMAIL = "ama.ops@bonarda.works"

SKILLS: dict[str, tuple[str, str]] = {
    "data-analysis": ("Data analysis", "Analyse de données"),
    "sql": ("SQL", "SQL"),
    "software-engineering": ("Software engineering", "Génie logiciel"),
    "devsecops": ("DevSecOps", "DevSecOps"),
    "python": ("Python", "Python"),
    "dashboarding": ("Dashboarding", "Tableaux de bord"),
    "project-management": ("Project management", "Gestion de projet"),
    "react": ("React", "React"),
    "translation-fr": ("French translation", "Traduction française"),
    "field-survey": ("Field survey", "Enquête de terrain"),
}

POSITIVE = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": True,
    "would_reengage": True,
}
MIXED = {
    "delivered_on_agreed_dates": True,
    "handled_scope_changes_without_escalation": False,
    "would_reengage": True,
}


@dataclass
class Past:
    """A completed engagement: months ago it ended, and who reviewed it."""

    months_ago: int
    reviewer: str  # "efua" | "luc"
    answers: dict[str, bool] = field(default_factory=lambda: dict(POSITIVE))
    skills: list[str] = field(default_factory=list)


@dataclass
class DemoWorker:
    key: str
    name: str
    region: str
    location: str
    languages: list[str]
    skills: dict[str, bool]  # slug -> verified
    availability: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    available_in_days: int | None = None
    cross_region: bool = False
    locale: str = "en"
    history: list[Past] = field(default_factory=list)


WORKERS = [
    DemoWorker(
        "Charlie",
        "Charles Gold",
        "GH",
        "Accra",
        ["en", "tw"],
        {"software-engineering": True, "devsecops": True, "python": True},
        history=[
            Past(2, "efua", skills=["software-engineering", "python"]),
            Past(5, "luc", skills=["software-engineering", "devsecops"]),
            Past(8, "efua"),
            Past(11, "luc"),
        ],
    ),
    DemoWorker(
        "kofi",
        "Kofi Mensah",
        "GH",
        "Accra",
        ["en", "tw"],
        {"data-analysis": True, "sql": True, "python": False},
        history=[
            Past(2, "efua", skills=["data-analysis", "sql"]),
            Past(5, "luc", skills=["data-analysis"]),
            Past(8, "efua"),
            Past(11, "luc"),
        ],
    ),
    DemoWorker(
        "abena",
        "Abena Owusu",
        "GH",
        "Kumasi",
        ["en"],
        {"data-analysis": True, "dashboarding": False},
        history=[Past(1, "efua"), Past(4, "luc"), Past(7, "efua")],
    ),
    DemoWorker(
        "yaw",
        "Yaw Darko",
        "GH",
        "Accra",
        ["en", "ga"],
        {"data-analysis": False, "sql": False, "python": False},
        history=[Past(18, "efua")],
    ),
    DemoWorker(
        "akosua",
        "Akosua Frimpong",
        "GH",
        "Takoradi",
        ["en"],
        {"data-analysis": False, "sql": False, "dashboarding": False},
    ),
    DemoWorker(
        "kojo",
        "Kojo Antwi",
        "GH",
        "Accra",
        ["en"],
        {"data-analysis": False, "sql": False},
        availability=AvailabilityStatus.AVAILABLE_FROM,
        available_in_days=10,
    ),
    DemoWorker(
        "mariam",
        "Mariam Bello",
        "GH",
        "Tamale",
        ["en", "ha"],
        {"data-analysis": False, "sql": False, "python": False},
    ),
    DemoWorker(
        "ibrahim",
        "Ibrahim Sule",
        "GH",
        "Tamale",
        ["en"],
        {"dashboarding": False, "data-analysis": False},
        history=[Past(8, "efua", answers=dict(MIXED))],
    ),
    DemoWorker(
        "esi",
        "Esi Quaye",
        "GH",
        "Cape Coast",
        ["en", "fr"],
        {"field-survey": False, "translation-fr": False},
        history=[Past(6, "luc", answers=dict(MIXED))],
    ),
    DemoWorker(
        "nana",
        "Nana Adjei",
        "GH",
        "Accra",
        ["en"],
        {"data-analysis": False, "python": False},
        availability=AvailabilityStatus.UNAVAILABLE,
    ),
    DemoWorker(
        "claire",
        "Claire Dubois",
        "EU",
        "Lyon",
        ["fr", "en"],
        {"data-analysis": True, "sql": False, "python": False},
        cross_region=True,
        locale="fr",
        history=[Past(3, "luc"), Past(9, "luc")],
    ),
    DemoWorker(
        "julien",
        "Julien Moreau",
        "EU",
        "Paris",
        ["fr"],
        {"react": False, "python": False},
        locale="fr",
    ),
    DemoWorker(
        "sophie",
        "Sophie Laurent",
        "EU",
        "Lille",
        ["fr", "en"],
        {"project-management": False, "translation-fr": False},
        locale="fr",
    ),
]


# Underused, qualified freelancers: the people the first-shot panel exists to
# surface once the top candidates are taken out of it (spec §7.4).
_NEWCOMERS: list[tuple[str, str, str, dict[str, bool], list[Past]]] = [
    ("Adwoa Sarpong", "GH", "Accra", {"data-analysis": False, "sql": False}, []),
    (
        "Kwabena Osei",
        "GH",
        "Kumasi",
        {"data-analysis": False, "sql": False, "dashboarding": False},
        [],
    ),
    ("Efia Boakye", "GH", "Ho", {"data-analysis": False, "sql": False}, [Past(10, "luc")]),
    ("Selorm Agbeko", "GH", "Ho", {"data-analysis": False, "sql": False, "python": False}, []),
    ("Afia Nyarko", "GH", "Sunyani", {"dashboarding": False, "data-analysis": False}, []),
    ("Kweku Ampofo", "GH", "Koforidua", {"dashboarding": False, "data-analysis": False}, []),
    (
        "Zainab Mahama",
        "GH",
        "Tamale",
        {"data-analysis": False, "sql": False, "dashboarding": False},
        [],
    ),
    ("Emeka Okafor", "GH", "Accra", {"data-analysis": False, "sql": False}, []),
    ("Léa Fontaine", "EU", "Grenoble", {"data-analysis": False, "python": False}, []),
    ("Hugo Bernard", "EU", "Lyon", {"data-analysis": False, "python": False}, [Past(9, "luc")]),
    (
        "Camille Roux",
        "EU",
        "Marseille",
        {"data-analysis": False, "python": False, "sql": False},
        [],
    ),
    ("Noah Lefebvre", "EU", "Lyon", {"data-analysis": False, "python": False}, []),
]
WORKERS += [
    DemoWorker(
        name.split()[0].lower(),
        name,
        region,
        city,
        ["fr", "en"] if region == "EU" else ["en"],
        skills,
        locale="fr" if region == "EU" else "en",
        history=history,
    )
    for name, region, city, skills, history in _NEWCOMERS
]


def _months_ago(months: int) -> date:
    return utcnow().date() - timedelta(days=30 * months)


def _staff(email: str, role: UserRole, subject: str) -> UserAccount:
    return UserAccount(
        email=email,
        role=role,
        auth_provider=AuthProvider.CORPORATE_SSO,
        oidc_subject=subject,
        status=AccountStatus.ACTIVE,
    )


async def seed(session: AsyncSession) -> bool:
    if await session.scalar(select(UserAccount.id).where(UserAccount.email == OPS_EMAIL)):
        return False
    now = utcnow()

    staff = {
        "ama": _staff(OPS_EMAIL, UserRole.PEOPLE_OPS, "demo-ama"),
        "kwame": _staff("kwame.ops@bonarda.works", UserRole.PEOPLE_OPS, "demo-kwame"),
        "efua": _staff("efua.pm@bonarda.works", UserRole.PM, "demo-efua"),
        "luc": _staff("luc.pm@bonarda.works", UserRole.PM, "demo-luc"),
        "fin": _staff("finance@bonarda.works", UserRole.FINANCE, "demo-fin"),
        "admin": _staff("admin@bonarda.works", UserRole.ADMIN, "demo-admin"),
    }
    session.add_all(staff.values())

    skills = {
        slug: Skill(slug=slug, name_i18n={"en": en, "fr": fr}) for slug, (en, fr) in SKILLS.items()
    }
    session.add_all(skills.values())
    await session.flush()

    def ids(*slugs: str) -> list[UUID]:
        return [skills[s].id for s in slugs]

    archive = {
        "GH": Project(name="Archive — Accra Retail Survey", data_region="GH"),
        "EU": Project(name="Archive — Lyon Transit Data", data_region="EU"),
    }
    live = [
        (
            Project(
                name="Volta Retail Analytics",
                client_name="Volta Foods",
                data_region="GH",
                required_skill_ids=ids("data-analysis", "sql"),
                starts_on=now.date() + timedelta(days=7),
            ),
            ["efua"],
        ),
        (
            Project(
                name="Kumasi Health Dashboard",
                client_name="Ashanti Health Trust",
                data_region="GH",
                required_skill_ids=ids("dashboarding", "data-analysis"),
                starts_on=now.date() + timedelta(days=14),
            ),
            ["efua"],
        ),
        (
            Project(
                name="Lyon Mobility Study",
                client_name="Métropole de Lyon",
                data_region="EU",
                required_skill_ids=ids("data-analysis", "python"),
                starts_on=now.date() + timedelta(days=10),
            ),
            ["luc"],
        ),
    ]
    session.add_all([*archive.values(), *(p for p, _ in live)])
    await session.flush()
    for project, pms in live:
        for pm in pms:
            session.add(
                ProjectStaff(project_id=project.id, user_account_id=staff[pm].id, active_from=now)
            )
    for project in archive.values():
        for pm in ("efua", "luc"):
            session.add(
                ProjectStaff(project_id=project.id, user_account_id=staff[pm].id, active_from=now)
            )

    workers: dict[str, Worker] = {}
    for spec in WORKERS:
        worker = Worker(
            full_name=spec.name,
            worker_type=WorkerType.FREELANCER,
            data_region=spec.region,
            status=WorkerStatus.DORMANT,
            onboarding_state=OnboardingState.PROFILE_COMPLETE,
            base_location=spec.location,
            languages=spec.languages,
            availability_status=spec.availability,
            available_from=now.date() + timedelta(days=spec.available_in_days)
            if spec.available_in_days
            else None,
        )
        session.add(worker)
        await session.flush()
        workers[spec.key] = worker
        first = unicodedata.normalize("NFKD", spec.name.split()[0]).encode("ascii", "ignore")
        email = f"{first.decode().lower()}@example.com"
        session.add(
            UserAccount(
                email=email,
                role=UserRole.WORKER,
                auth_provider=AuthProvider.MAGIC_LINK,
                worker_id=worker.id,
                locale=spec.locale,
            )
        )
        for slug, verified in spec.skills.items():
            session.add(
                SkillClaim(
                    worker_id=worker.id,
                    skill_id=skills[slug].id,
                    verification_status=VerificationStatus.BONARDA_VERIFIED
                    if verified
                    else VerificationStatus.SELF_REPORTED,
                )
            )
        if spec.cross_region:
            session.add(
                Consent(
                    worker_id=worker.id,
                    purpose=ConsentPurpose.CROSS_REGION_MATCHING,
                    granted=True,
                    legal_basis="consent",
                    granted_at=now,
                )
            )
        for past in spec.history:
            end = _months_ago(past.months_ago)
            start = end - timedelta(days=45)
            engagement = Engagement(
                worker_id=worker.id,
                project_id=archive[spec.region].id,
                path=EngagementPath.FIRST_TIME,
                status=EngagementStatus.COMPLETED,
                start_date=start,
                end_date=end,
                rate=Decimal("450.00") if spec.region == "GH" else Decimal("380.00"),
                currency="GHS" if spec.region == "GH" else "EUR",
                work_mode=WorkMode.REMOTE,
                contract_terms={"scope": "Data collection and analysis", "access_notes": None},
                confirmed_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC)
                - timedelta(days=5),
                signed_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC)
                - timedelta(days=3),
                billable_start_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                completed_at=datetime.combine(end, datetime.min.time(), tzinfo=UTC),
            )
            session.add(engagement)
            await session.flush()
            session.add(
                Feedback(
                    engagement_id=engagement.id,
                    reviewer_id=staff[past.reviewer].id,
                    structured_answers=past.answers,
                    free_text="Clear communication and solid delivery.",
                    skill_ids_demonstrated=ids(*past.skills),
                )
            )

    # One live engagement: Kofi is on an archive project right now.
    session.add(
        Engagement(
            worker_id=workers["kofi"].id,
            project_id=archive["GH"].id,
            path=EngagementPath.REACTIVATION,
            status=EngagementStatus.ACTIVE,
            start_date=now.date() - timedelta(days=10),
            end_date=now.date() + timedelta(days=20),
            rate=Decimal("480.00"),
            currency="GHS",
            work_mode=WorkMode.HYBRID,
            location="Accra",
            contract_terms={"scope": "Retail survey follow-up", "access_notes": "Office badge"},
            confirmed_at=now - timedelta(days=14),
            signed_at=now - timedelta(days=12),
            billable_start_at=now - timedelta(days=10),
            payroll_signaled_at=now - timedelta(days=10),
        )
    )
    workers["kofi"].status = WorkerStatus.ACTIVE
    await session.flush()

    # Esi disputes the mixed feedback she received.
    esi_feedback = await session.scalar(
        select(Feedback.id)
        .join(Engagement, Engagement.id == Feedback.engagement_id)
        .where(Engagement.worker_id == workers["esi"].id)
    )
    if esi_feedback is not None:
        session.add(
            Dispute(
                worker_id=workers["esi"].id,
                target_type=DisputeTargetType.FEEDBACK,
                target_id=esi_feedback,
                reason="The scope changed twice without notice; I escalated as agreed.",
                due_at=now + timedelta(days=2),
            )
        )
    await session.commit()

    # The demo pool is small: excluding the top 10 candidates would leave the
    # first-shot panel empty. Matching v2 goes through the real two-person flow.
    matching = await active_matching(session)
    rules = matching.rules.model_dump(mode="json")
    rules["first_shot"]["exclude_top_candidates"] = 3
    ama = Actor(user_id=staff["ama"].id, role=UserRole.PEOPLE_OPS)
    kwame = Actor(user_id=staff["kwame"].id, role=UserRole.PEOPLE_OPS)
    policies = PolicyService(session)
    proposed = await policies.propose(
        ama,
        PolicyKind.MATCHING,
        PolicyCreate(rules=rules, notes="Demo pool: exclude only the top 3 from first-shot"),
    )
    await policies.activate(kwame, PolicyKind.MATCHING, proposed.version)
    await session.commit()

    await recalculate_all_standing(session)
    await session.commit()
    await rebuild_all(session)
    await run_concentration_rollup(session)
    await session.commit()
    return True


async def main() -> None:
    settings = get_settings()
    configure_logging(json_logs=False)
    engine = create_engine(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            seeded = await seed(session)
        log.info("demo.seed", seeded=seeded)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
