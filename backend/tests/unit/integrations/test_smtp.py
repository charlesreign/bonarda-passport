from typing import Any

import pytest

from app.modules.integrations import smtp
from app.modules.integrations.smtp import SmtpMailer


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append((message, kwargs))
        return {}, "OK"

    monkeypatch.setattr(smtp.aiosmtplib, "send", fake_send)
    return calls


async def test_sends_plain_text_message_with_headers(
    sent: list[tuple[Any, dict[str, Any]]],
) -> None:
    mailer = SmtpMailer("smtp://mailpit:1025", "Bonarda <no-reply@bonarda.works>")

    await mailer.send(to="kofi@example.com", subject="Hello", body="Body text")

    message, kwargs = sent[0]
    assert message["From"] == "Bonarda <no-reply@bonarda.works>"
    assert message["To"] == "kofi@example.com"
    assert message["Subject"] == "Hello"
    assert message.get_content().strip() == "Body text"
    assert (kwargs["hostname"], kwargs["port"], kwargs["use_tls"]) == ("mailpit", 1025, False)
    assert kwargs["username"] is None
    assert kwargs["password"] is None


async def test_smtps_url_uses_implicit_tls_default_port_and_decoded_credentials(
    sent: list[tuple[Any, dict[str, Any]]],
) -> None:
    mailer = SmtpMailer("smtps://apikey:p%40ss@smtp.example.com", "no-reply@bonarda.works")

    await mailer.send(to="a@b.c", subject="s", body="b")

    kwargs = sent[0][1]
    assert (kwargs["hostname"], kwargs["port"], kwargs["use_tls"]) == (
        "smtp.example.com",
        465,
        True,
    )
    assert (kwargs["username"], kwargs["password"]) == ("apikey", "p@ss")


@pytest.mark.parametrize("url", ["http://mail.example.com", "smtp://"])
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError, match="smtp_url"):
        SmtpMailer(url, "no-reply@bonarda.works")
