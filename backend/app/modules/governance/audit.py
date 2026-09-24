"""The audit-trail reader (FR-7.3): newest first, keyset-paged on the row id."""

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.governance.repository import AuditLogRepository
from app.modules.governance.schemas import AuditEntryRead, AuditLogPage

# A positive bigint that fits in 18 digits.
_ROW_ID = re.compile(r"[1-9][0-9]{0,17}")


def _before_id(cursor: str) -> int:
    raw = decode_cursor(cursor, ("id",))["id"]
    if not _ROW_ID.fullmatch(raw):
        raise BadRequest("Invalid cursor", code="invalid_cursor")
    return int(raw)


async def audit_trail(
    session: AsyncSession,
    *,
    target_type: str | None,
    target_id: UUID | None,
    action: str | None,
    cursor: str | None,
    limit: int,
) -> AuditLogPage:
    if target_id is not None and target_type is None:
        raise BadRequest("target_id needs target_type", code="target_type_required")
    rows = await AuditLogRepository(session).page(
        target_type=target_type,
        target_id=target_id,
        action=action,
        before_id=_before_id(cursor) if cursor is not None else None,
        limit=limit + 1,
    )
    page = rows[:limit]
    return AuditLogPage(
        items=[AuditEntryRead.model_validate(row) for row in page],
        next_cursor=encode_cursor({"id": str(page[-1].id)}) if len(rows) > limit else None,
    )
