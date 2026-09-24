"""The MVA's fairness loop (spec §10): a PM staffing a project sees scored
candidates and, on the same page, a first-shot panel of qualified underused
workers; shortlisting one opens their detail; the roster follows events."""

import copy
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.time import utcnow
from app.modules.passport.enums import VerificationStatus
from app.modules.passport.models import Skill, SkillClaim
from tests.support import (
    _seed_policy_rows,
    bearer,
    make_engagement,
    make_project,
    make_ready_worker,
    make_user,
    refresh_roster,
)

Drain = Callable[[], Awaitable[None]]


async def test_candidates_first_shot_and_shortlisting(
    client: AsyncClient, session: AsyncSession, settings: Settings, drain: Drain
) -> None:
    # People Ops set a matching policy suited to a small pool.
    rules: dict[str, Any] = copy.deepcopy(
        next(p["rules"] for p in _seed_policy_rows() if p["kind"] == "matching")
    )
    rules["first_shot"]["exclude_top_candidates"] = 1
    author = await make_user(session, role=UserRole.PEOPLE_OPS)
    approver = await make_user(session, role=UserRole.PEOPLE_OPS)
    proposed = await client.post(
        "/api/v1/policies/matching/versions",
        json={"rules": rules},
        headers=bearer(settings, author),
    )
    assert (
        await client.post(
            f"/api/v1/policies/matching/versions/{proposed.json()['version']}/activate",
            headers=bearer(settings, approver),
        )
    ).status_code == 200

    # Three qualified workers: Ama is verified and busy, Kofi and Esi are underused.
    pm = await make_user(session, role=UserRole.PM)
    ama, _ = await make_ready_worker(session, email="ama@example.com", full_name="Ama")
    kofi, _ = await make_ready_worker(session, email="kofi@example.com", full_name="Kofi")
    esi, esi_account = await make_ready_worker(session, email="esi@example.com", full_name="Esi")
    skill = (await session.scalars(select(Skill))).one()
    ama_claim = (
        await session.scalars(select(SkillClaim).where(SkillClaim.worker_id == ama.id))
    ).one()
    ama_claim.verification_status = VerificationStatus.BONARDA_VERIFIED
    await session.commit()
    past = await make_project(session, name="Past")
    for days in (30, 60):
        await make_engagement(
            session,
            worker_id=ama.id,
            project_id=past.id,
            start_date=utcnow().date() - timedelta(days=days),
        )
    project = await make_project(
        session,
        staff=[pm],
        name="Tema",
        required_skill_ids=[skill.id],
        starts_on=utcnow().date() + timedelta(days=7),
    )
    await refresh_roster(session)
    headers = bearer(settings, pm)

    # 1. Candidates: Ama ranks first on verified coverage.
    candidates = (
        await client.get(f"/api/v1/projects/{project.id}/candidates", headers=headers)
    ).json()["items"]
    assert candidates[0]["worker"]["display_name"] == "Ama"
    assert candidates[0]["score_breakdown"]["policy_version"] == 2

    # 2. First-shot: Ama is excluded (top candidate and busy); Kofi and Esi are shown.
    panel = (await client.get(f"/api/v1/projects/{project.id}/first-shot", headers=headers)).json()
    shown = {i["worker"]["display_name"]: i["worker"]["worker_id"] for i in panel["items"]}
    assert set(shown) == {"Kofi", "Esi"}

    # 3. Shortlisting Esi opens her detail view.
    reviewed = await client.post(
        f"/api/v1/projects/{project.id}/first-shot/{shown['Esi']}/review",
        json={"outcome": "shortlisted"},
        headers=headers,
    )
    assert reviewed.status_code == 200
    detail = await client.get(f"/api/v1/workers/{shown['Esi']}", headers=headers)
    assert detail.json()["view"] == "detail"

    # 4. Esi becomes unavailable; the roster follows, and she stays in the
    # candidates with 0 availability points.
    await client.patch(
        "/api/v1/workers/me",
        json={"availability_status": "unavailable"},
        headers=bearer(settings, esi_account),
    )
    await drain()
    after = (await client.get(f"/api/v1/projects/{project.id}/candidates", headers=headers)).json()
    scores = {c["worker"]["worker_id"]: c["score_breakdown"] for c in after["items"]}
    assert scores[str(esi.id)]["availability"]["points"] == 0.0
    assert scores[str(kofi.id)]["availability"]["points"] == 0.15
