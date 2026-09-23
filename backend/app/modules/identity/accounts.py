"""Account operations other modules need (via identity.service)."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.enums import AuthProvider, UserRole
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.identity.models import UserAccount
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


async def provision_worker_account(
    session: AsyncSession, *, actor: Actor, email: str, worker_id: UUID, locale: str
) -> UUID:
    """Creates the sign-in account a worker's passport hangs off (FR-9.2, FR-9.6)."""
    users = UserRepository(session)
    try:
        async with session.begin_nested():
            user = users.add(
                UserAccount(
                    email=email,
                    role=UserRole.WORKER,
                    auth_provider=AuthProvider.MAGIC_LINK,
                    worker_id=worker_id,
                    locale=locale,
                )
            )
            await session.flush()
    except IntegrityError as exc:
        raise Conflict("An account with this email already exists", code="email_in_use") from exc
    await write_audit(
        session,
        actor=actor,
        action="user.provisioned",
        target_type="user_account",
        target_id=user.id,
        after={"email": user.email, "role": UserRole.WORKER.value},
    )
    return user.id
