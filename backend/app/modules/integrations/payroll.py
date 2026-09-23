from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PayrollActivation:
    engagement_id: UUID
    worker_id: UUID
    start_date: date
    rate: Decimal
    currency: str


class PayrollAdapter(Protocol):
    async def signal_active(self, activation: PayrollActivation) -> None:
        """Tells payments an engagement is billable (FR-8.3). Idempotent per
        engagement_id; payment logic stays in the payments system."""
        ...


class FakePayrollAdapter:
    def __init__(self) -> None:
        self.activations: dict[UUID, PayrollActivation] = {}

    async def signal_active(self, activation: PayrollActivation) -> None:
        self.activations[activation.engagement_id] = activation
