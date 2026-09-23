from email.message import EmailMessage
from urllib.parse import unquote, urlsplit

import aiosmtplib

SMTP_TIMEOUT_SECONDS = 10.0


class SmtpMailer:
    """Sends plain-text mail over SMTP. `smtps://` means implicit TLS (default
    port 465). `smtp://` upgrades with STARTTLS: when `require_tls` is true
    (the default), aiosmtplib is told to fail the send rather than fall back
    to plaintext if the server won't upgrade, which closes the STARTTLS-
    stripping hole where an on-path attacker strips the STARTTLS
    advertisement to force plaintext and expose AUTH credentials and message
    bodies. Pass `require_tls=False` only for a trusted local relay (e.g.
    Mailpit in dev/test) where opportunistic STARTTLS is acceptable."""

    def __init__(self, url: str, sender: str, *, require_tls: bool = True) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("smtp", "smtps"):
            raise ValueError("smtp_url must start with smtp:// or smtps://")
        if not parts.hostname:
            raise ValueError("smtp_url must include a host")
        self._implicit_tls = parts.scheme == "smtps"
        self._host = parts.hostname
        self._port = parts.port or (465 if self._implicit_tls else 25)
        self._username = unquote(parts.username) if parts.username else None
        self._password = unquote(parts.password) if parts.password else None
        self._sender = sender
        self._require_tls = require_tls

    @property
    def requires_tls(self) -> bool:
        return self._require_tls

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if self._implicit_tls:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=True,
                timeout=SMTP_TIMEOUT_SECONDS,
            )
        else:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=False,
                start_tls=True if self._require_tls else None,
                timeout=SMTP_TIMEOUT_SECONDS,
            )
