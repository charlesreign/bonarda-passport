import base64
import json

import pytest

from app.core.errors import BadRequest
from app.core.pagination import decode_cursor, encode_cursor


def test_a_cursor_round_trips() -> None:
    cursor = encode_cursor({"id": "42", "due_at": "2026-10-01T00:00:00+00:00"})

    assert decode_cursor(cursor, ("due_at", "id")) == {
        "id": "42",
        "due_at": "2026-10-01T00:00:00+00:00",
    }


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(json.dumps(["id"]).encode()).decode(),
        encode_cursor({"other": "1"}),
        encode_cursor({"id": "1", "extra": "2"}),
        base64.urlsafe_b64encode(json.dumps({"id": 1}).encode()).decode(),
    ],
)
def test_a_malformed_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(BadRequest) as excinfo:
        decode_cursor(cursor, ("id",))

    assert excinfo.value.code == "invalid_cursor"
