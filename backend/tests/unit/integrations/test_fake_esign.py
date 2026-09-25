from app.modules.integrations.service import FakeEsignAdapter


async def test_voiding_twice_is_harmless() -> None:
    esign = FakeEsignAdapter()

    await esign.void("fake-env-1")
    await esign.void("fake-env-1")

    assert esign.voided == {"fake-env-1"}
