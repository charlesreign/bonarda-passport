from app.core.i18n import t


def test_translates_with_parameters() -> None:
    assert "15" in t("magic_link.body", "fr", minutes=15, link="https://x")
    assert t("magic_link.subject", "fr") == "Votre lien de connexion Bonarda"


def test_unknown_locale_falls_back_to_english() -> None:
    assert t("magic_link.subject", "sw") == "Your Bonarda sign-in link"
