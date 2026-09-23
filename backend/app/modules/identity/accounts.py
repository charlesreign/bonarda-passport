"""Account operations other modules need (via identity.service)."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.writer import write_audit
from app.core.context import Actor
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.errors import Conflict, NotFound
from app.core.outbox.writer import emit_event
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import UserRepository, normalize_email
from app.modules.identity.schemas import (
    AccountContact,
    MagicLinkRequested,
    SignInPurpose,
    WorkerAccountRef,
)


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
    email = normalize_email(email)
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
    # Audit rows about workers carry no contact data (spec §6.3 erasure): the
    # append-only audit log rejects UPDATE/DELETE, so an email written here
    # would survive the worker's own erasure. target_id identifies the row.
    await write_audit(
        session,
        actor=actor,
        action="user.provisioned",
        target_type="user_account",
        target_id=user.id,
        after={"role": UserRole.WORKER.value},
    )
    return user.id


async def find_worker_account(session: AsyncSession, email: str) -> WorkerAccountRef | None:
    """Looks up an existing worker sign-in account by email (normalized here so
    audit/lookups agree), for an idempotent re-invite. None unless the account
    exists, has role WORKER, a worker_id and is ACTIVE (a revoked account is
    not "still invited")."""
    user = await UserRepository(session).get_by_email(normalize_email(email))
    if (
        user is None
        or user.role is not UserRole.WORKER
        or user.worker_id is None
        or user.status is not AccountStatus.ACTIVE
    ):
        return None
    return WorkerAccountRef(user_id=user.id, worker_id=user.worker_id)


async def worker_contact(session: AsyncSession, worker_id: UUID) -> AccountContact | None:
    user = await session.scalar(select(UserAccount).where(UserAccount.worker_id == worker_id))
    if user is None:
        return None
    return AccountContact(email=user.email, locale=user.locale)


async def active_pm_ids(session: AsyncSession, user_ids: Iterable[UUID]) -> set[UUID]:
    """The subset of `user_ids` that are active project managers."""
    ids = list(user_ids)
    if not ids:
        return set()
    rows = await session.scalars(
        select(UserAccount.id).where(
            UserAccount.id.in_(ids),
            UserAccount.role == UserRole.PM,
            UserAccount.status == AccountStatus.ACTIVE,
        )
    )
    return set(rows.all())
