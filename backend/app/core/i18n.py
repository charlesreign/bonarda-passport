"""Server-side message catalog (NFR-8.1). The SPA owns UI strings; the backend
only needs text it sends itself, such as email."""

from typing import Literal

Locale = Literal["en", "fr"]
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "fr")

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "magic_link.subject": "Your Bonarda sign-in link",
        "magic_link.body": (
            "Use this link to sign in to your Bonarda passport. "
            "It works once and expires in {minutes} minutes:\n\n{link}\n\n"
            "If you did not ask for it, you can ignore this email."
        ),
    },
    "fr": {
        "magic_link.subject": "Votre lien de connexion Bonarda",
        "magic_link.body": (
            "Utilisez ce lien pour vous connecter à votre passeport Bonarda. "
            "Il ne fonctionne qu'une fois et expire dans {minutes} minutes :\n\n{link}\n\n"
            "Si vous ne l'avez pas demandé, ignorez cet e-mail."
        ),
    },
}
DEFAULT_LOCALE = "en"


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    catalog = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = catalog.get(key, MESSAGES[DEFAULT_LOCALE][key])
    return template.format(**params)
