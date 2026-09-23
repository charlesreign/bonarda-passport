import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.mail import ConsoleMailer
from app.modules.integrations.service import SmtpMailer, build_mailer


def test_smtp_url_gives_smtp_mailer(settings: Settings) -> None:
    configured = settings.model_copy(update={"smtp_url": SecretStr("smtp://mailpit:1025")})

    assert isinstance(build_mailer(configured), SmtpMailer)


def test_dev_and_test_without_smtp_log_to_console(settings: Settings) -> None:
    assert isinstance(build_mailer(settings), ConsoleMailer)
    assert isinstance(build_mailer(settings.model_copy(update={"env": "dev"})), ConsoleMailer)


def test_production_without_smtp_refuses_to_start(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="mailer"):
        build_mailer(settings.model_copy(update={"env": "prod"}))


def test_production_with_smtp_requires_tls(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"env": "prod", "smtp_url": SecretStr("smtp://relay:587")}
    )

    mailer = build_mailer(configured)

    assert isinstance(mailer, SmtpMailer)
    assert mailer.requires_tls is True


def test_dev_with_smtp_does_not_require_tls(settings: Settings) -> None:
    configured = settings.model_copy(update={"smtp_url": SecretStr("smtp://mailpit:1025")})

    mailer = build_mailer(configured)

    assert isinstance(mailer, SmtpMailer)
    assert mailer.requires_tls is False
