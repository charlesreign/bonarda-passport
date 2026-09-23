from email.message import EmailMessage
from urllib.parse import unquote, urlsplit

import aiosmtplib

SMTP_TIMEOUT_SECONDS = 10.0


class SmtpMailer:
    """Sends plain-text mail over SMTP. `smtps://` means implicit TLS (default
    port 465); `smtp://` upgrades with STARTTLS when the server offers it."""

    def __init__(self, url: str, sender: str) -> None:
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

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(
            message,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._implicit_tls,
            timeout=SMTP_TIMEOUT_SECONDS,
        )
