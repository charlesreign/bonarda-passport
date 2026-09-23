"""Public interface of the integrations module."""

from app.core.config import NON_PRODUCTION_ENVS, Settings
from app.core.mail import ConsoleMailer, Mailer
from app.modules.integrations.smtp import SmtpMailer


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_url is not None:
        return SmtpMailer(
            settings.smtp_url.get_secret_value(),
            settings.mail_from,
            require_tls=settings.env not in NON_PRODUCTION_ENVS,
        )
    if settings.env in NON_PRODUCTION_ENVS:
        # ConsoleMailer logs full sign-in links: acceptable only on a
        # developer's own machine or in tests.
        return ConsoleMailer()
    raise RuntimeError("A real mailer must be configured outside dev/test: set SMTP_URL")


__all__ = ["SmtpMailer", "build_mailer"]
