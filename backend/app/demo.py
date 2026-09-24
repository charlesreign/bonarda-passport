"""Demo-only routes. Mounted by create_app only when DEMO_MODE is on and the
environment is dev/test: pick a seeded account to sign in as (no IdP needed),
and play the e-signature provider's "signed" callback."""

from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db.session import SessionDep
from app.core.deps import SettingsDep
from app.core.enums import AccountStatus, UserRole
from app.core.errors import Conflict, NotFound
from app.modules.engagements.contracts import ContractService
from app.modules.engagements.models import Engagement
from app.modules.engagements.schemas import EsignWebhook
from app.modules.identity.models import UserAccount
from app.modules.identity.router import set_refresh_cookie
from app.modules.identity.schemas import TokenResponse
from app.modules.identity.service import CurrentActor
from app.modules.identity.sessions import SessionService
from app.modules.passport.models import Worker

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


class DemoAccount(BaseModel):
    id: UUID
    email: str
    role: UserRole
    name: str


class DemoLogin(BaseModel):
    user_id: UUID


@router.get("/accounts")
async def demo_accounts(session: SessionDep) -> list[DemoAccount]:
    rows = await session.execute(
        select(UserAccount, Worker.full_name)
        .outerjoin(Worker, Worker.id == UserAccount.worker_id)
        .where(UserAccount.status == AccountStatus.ACTIVE)
        .order_by(UserAccount.role, UserAccount.email)
    )
    return [
        DemoAccount(id=user.id, email=user.email, role=user.role, name=name or user.email)
        for user, name in rows
    ]


@router.post("/login")
async def demo_login(
    body: DemoLogin, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    user = await session.get(UserAccount, body.user_id)
    if user is None or user.status is not AccountStatus.ACTIVE:
        raise NotFound("Account not found", code="account_not_found")
    issued = await SessionService(session, settings).start(user, amr=["demo"])
    set_refresh_cookie(response, settings, issued)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post("/engagements/{engagement_id}/sign", status_code=204)
async def demo_sign_contract(engagement_id: UUID, actor: CurrentActor, session: SessionDep) -> None:
    """Plays the fake e-sign provider's signed webhook for a sent contract.
    Only the freelancer the contract is for can sign it; anyone else gets the
    same 404 as for an unknown engagement."""
    engagement = await session.get(Engagement, engagement_id)
    if engagement is None or actor.worker_id != engagement.worker_id:
        raise NotFound("Engagement not found", code="engagement_not_found")
    if engagement.esign_envelope_id is None:
        raise Conflict("The contract has not been sent yet; try again", code="contract_not_sent")
    await ContractService(session).handle_webhook(
        EsignWebhook(envelope_id=engagement.esign_envelope_id, event="signed")
    )
