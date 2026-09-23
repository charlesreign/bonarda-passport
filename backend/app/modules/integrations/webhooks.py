import hashlib
import hmac
from datetime import datetime

SIGNATURE_TOLERANCE_SECONDS = 300


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    *,
    timestamp_header: str | None,
    signature_header: str | None,
    body: bytes,
    now: datetime,
) -> bool:
    """HMAC over "<timestamp>.<body>"; the timestamp bounds replay (spec §8.1)."""
    if not timestamp_header or not signature_header:
        return False
    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return False
    if abs(now.timestamp() - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature_header)
