from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.integrations.service import (
    ContractDocument,
    FakeEsignAdapter,
    FakePayrollAdapter,
    PayrollActivation,
    build_esign,
    build_payroll,
)


def _document() -> ContractDocument:
    return ContractDocument(
        engagement_id=uuid4(),
        signer_name="Kofi Mensah",
        signer_email="kofi@example.com",
        project_name="Project Volta",
        start_date=date(2026, 10, 1),
        end_date=None,
        rate=Decimal("450.00"),
        currency="GHS",
        work_mode="remote",
        scope="Build the data pipeline",
        access_notes=None,
    )


async def test_fake_esign_is_idempotent_per_engagement() -> None:
    esign = FakeEsignAdapter()
    document = _document()

    first = await esign.send_contract(document)
    second = await esign.send_contract(document)

    assert first == second == f"fake-env-{document.engagement_id}"
    assert list(esign.sent) == [document.engagement_id]


async def test_fake_payroll_records_one_activation_per_engagement() -> None:
    payroll = FakePayrollAdapter()
    activation = PayrollActivation(
        engagement_id=uuid4(),
        worker_id=uuid4(),
        start_date=date(2026, 10, 1),
        rate=Decimal("450.00"),
        currency="GHS",
    )

    await payroll.signal_active(activation)
    await payroll.signal_active(activation)

    assert list(payroll.activations.values()) == [activation]


def test_fakes_are_built_in_dev_and_test(settings: Settings) -> None:
    assert isinstance(build_esign(settings), FakeEsignAdapter)
    assert isinstance(build_payroll(settings), FakePayrollAdapter)


@pytest.mark.parametrize("builder", [build_esign, build_payroll])
def test_fakes_are_refused_in_production(
    settings: Settings, builder: Callable[[Settings], object]
) -> None:
    with pytest.raises(RuntimeError, match="adapter"):
        builder(settings.model_copy(update={"env": "prod"}))
