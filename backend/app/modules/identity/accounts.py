"""Account operations other modules need (via identity.service)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.outbox.writer import emit_event
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import AccountContact, MagicLinkRequested, SignInPurpose


async def account_contact(session: AsyncSession, user_id: UUID) -> AccountContact:
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise NotFound("Account not found", code="account_not_found")
    return AccountContact(email=user.email, locale=user.locale)


async def request_sign_in_link(
    session: AsyncSession, user_id: UUID, *, purpose: SignInPurpose
) -> None:
    """Queues a sign-in link. The worker process issues the token and sends
    the mail, so no request's response time depends on the mail server."""
    await emit_event(session, MagicLinkRequested(aggregate_id=user_id, purpose=purpose))
