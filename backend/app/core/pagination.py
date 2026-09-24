"""Opaque keyset cursors (spec §7.2). A cursor is base64 JSON of string
values; callers parse and validate each value themselves."""

import base64
import binascii
import json

from app.core.errors import BadRequest


def _invalid() -> BadRequest:
    return BadRequest("Invalid cursor", code="invalid_cursor")


def encode_cursor(values: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str, keys: tuple[str, ...]) -> dict[str, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError) as exc:
        raise _invalid() from exc
    if not isinstance(data, dict) or set(data) != set(keys):
        raise _invalid()
    if not all(isinstance(data[key], str) for key in keys):
        raise _invalid()
    return {key: data[key] for key in keys}
