from typing import Annotated, Protocol

import structlog
from fastapi import Depends, Request

log = structlog.get_logger(__name__)


class Mailer(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    """Development only: writes mail to the log. Plan 6 wires SMTP (Mailpit)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        log.info("mail.console", to=to, subject=subject, body=body)


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer


MailerDep = Annotated[Mailer, Depends(get_mailer)]
