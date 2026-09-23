from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ContractDocument:
    engagement_id: UUID
    signer_name: str
    signer_email: str
    project_name: str
    start_date: date
    end_date: date | None
    rate: Decimal
    currency: str
    work_mode: str
    scope: str
    access_notes: str | None


class EsignAdapter(Protocol):
    async def send_contract(self, document: ContractDocument) -> str:
        """Sends the envelope and returns its id. Must be idempotent per
        engagement_id: a retried handler must not create a second envelope."""
        ...


class FakeEsignAdapter:
    """Dev/test stand-in. Records what it would send; never signs by itself."""

    def __init__(self) -> None:
        self.sent: dict[UUID, ContractDocument] = {}

    async def send_contract(self, document: ContractDocument) -> str:
        self.sent[document.engagement_id] = document
        return f"fake-env-{document.engagement_id}"
