from app.modules.governance.enums import DisputeTargetType
from app.wiring import dispute_target_owners


def test_every_target_type_has_an_owner_lookup() -> None:
    assert set(dispute_target_owners()) == set(DisputeTargetType)
