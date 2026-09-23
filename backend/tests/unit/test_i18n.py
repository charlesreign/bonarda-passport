from app.core.i18n import MESSAGES, SUPPORTED_LOCALES, t


def test_translates_with_parameters() -> None:
    assert "15" in t("magic_link.body", "fr", minutes=15, link="https://x")
    assert t("magic_link.subject", "fr") == "Votre lien de connexion Bonarda"


def test_unknown_locale_falls_back_to_english() -> None:
    assert t("magic_link.subject", "sw") == "Your Bonarda sign-in link"


def test_every_locale_defines_the_same_keys() -> None:
    assert set(MESSAGES) == set(SUPPORTED_LOCALES)
    assert {frozenset(catalog) for catalog in MESSAGES.values()} == {frozenset(MESSAGES["en"])}
