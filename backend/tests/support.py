import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic.config import Config
from app.core.config import Settings
from app.core.enums import AccountStatus, AuthProvider, UserRole
from app.core.outbox.models import OutboxEvent
from app.core.outbox.processing import process_event
from app.core.outbox.registry import HandlerRegistry
from app.core.time import utcnow
from app.modules.identity.models import UserAccount
from app.modules.identity.tokens import issue_access_token

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
) -> UserAccount:
    is_worker = role is UserRole.WORKER
    user = UserAccount(
        email=(email or f"{uuid4().hex[:10]}@example.com").strip().lower(),
        role=role,
        auth_provider=AuthProvider.MAGIC_LINK if is_worker else AuthProvider.CORPORATE_SSO,
        status=status,
        oidc_subject=oidc_subject if not is_worker else None,
        worker_id=(worker_id or uuid4()) if is_worker else None,
    )
    session.add(user)
    await session.commit()
    return user


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
