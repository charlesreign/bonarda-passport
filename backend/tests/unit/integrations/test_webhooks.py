from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.modules.integrations.service import sign_payload, verify_signature

SECRET = "esign-webhook-secret-for-tests-0123456789"
BODY = b'{"envelope_id":"fake-env-1","event":"signed"}'


def _headers(ts: int, body: bytes = BODY, secret: str = SECRET) -> dict[str, str]:
    return {"timestamp_header": str(ts), "signature_header": sign_payload(secret, ts, body)}


def test_valid_signature_verifies() -> None:
    now = utcnow()

    assert verify_signature(SECRET, body=BODY, now=now, **_headers(int(now.timestamp())))


@pytest.mark.parametrize(
    "case",
    ["tampered_body", "wrong_secret", "stale", "future", "missing", "non_numeric"],
)
def test_invalid_signatures_are_rejected(case: str) -> None:
    now = utcnow()
    ts = int(now.timestamp())
    kwargs: dict[str, str | None] = dict(_headers(ts))
    body = BODY
    if case == "tampered_body":
        body = BODY.replace(b"signed", b"declined")
    elif case == "wrong_secret":
        kwargs = dict(_headers(ts, secret="another-secret-0123456789-0123456789"))
    elif case == "stale":
        kwargs = dict(_headers(int((now - timedelta(minutes=6)).timestamp())))
    elif case == "future":
        kwargs = dict(_headers(int((now + timedelta(minutes=6)).timestamp())))
    elif case == "missing":
        kwargs = {"timestamp_header": None, "signature_header": None}
    elif case == "non_numeric":
        kwargs["timestamp_header"] = "yesterday"

    assert not verify_signature(SECRET, body=body, now=now, **kwargs)
