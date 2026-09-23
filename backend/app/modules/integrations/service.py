"""Public interface of the integrations module."""

from app.core.config import NON_PRODUCTION_ENVS, Settings
from app.core.mail import ConsoleMailer, Mailer
from app.modules.integrations.esign import ContractDocument, EsignAdapter, FakeEsignAdapter
from app.modules.integrations.payroll import (
    FakePayrollAdapter,
    PayrollActivation,
    PayrollAdapter,
)
from app.modules.integrations.smtp import SmtpMailer
from app.modules.integrations.webhooks import sign_payload, verify_signature


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


def build_esign(settings: Settings) -> EsignAdapter:
    if settings.env not in NON_PRODUCTION_ENVS:
        raise RuntimeError("A real e-signature adapter must be configured outside dev/test")
    return FakeEsignAdapter()


def build_payroll(settings: Settings) -> PayrollAdapter:
    if settings.env not in NON_PRODUCTION_ENVS:
        raise RuntimeError("A real payroll adapter must be configured outside dev/test")
    return FakePayrollAdapter()


__all__ = [
    "ContractDocument",
    "EsignAdapter",
    "FakeEsignAdapter",
    "FakePayrollAdapter",
    "PayrollActivation",
    "PayrollAdapter",
    "SmtpMailer",
    "build_esign",
    "build_mailer",
    "build_payroll",
    "sign_payload",
    "verify_signature",
]
