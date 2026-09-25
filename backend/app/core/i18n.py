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
        "invitation.subject": "You're invited to Bonarda Works",
        "invitation.body": (
            "Bonarda Works has created a passport for you. Use this link to sign in "
            "and complete your profile. It works once and expires in {minutes} minutes:"
            "\n\n{link}\n\n"
            "If it has expired, request a new link at {sign_in_url}."
        ),
        "engagement_confirmed.subject": "Your engagement on {project} has started",
        "engagement_confirmed.body": (
            "Your contract for {project} is signed and your engagement is active from "
            "{start_date}. You can see it on your Bonarda passport."
        ),
        "feedback_due.subject": "Feedback due for {worker} on {project}",
        "feedback_due.body": (
            "{worker}'s engagement on {project} is complete. Please submit feedback: "
            "it is how their standing reflects their work."
        ),
        "standing_changed.subject": "Your Bonarda standing has changed",
        "standing_changed.body": (
            "Your standing changed from {previous} to {tier}. Your passport shows the "
            "signals and the policy behind it. If you think it is wrong, you can dispute "
            "it from your passport."
        ),
        "tier.unrated": "Unrated",
        "tier.tier_1": "Tier 1",
        "tier.tier_2": "Tier 2",
        "dispute_resolved.subject": "Your dispute has been resolved",
        "dispute_resolved.body.upheld": "People Ops upheld your dispute.\n\nTheir notes:\n{notes}",
        "dispute_resolved.body.rejected": (
            "People Ops reviewed your dispute and did not uphold it.\n\nTheir notes:\n{notes}"
        ),
        "dispute_sla.subject": "Disputes: {overdue} overdue, {due_soon} due soon",
        "dispute_sla.body": "These open disputes need a decision:\n\n{lines}",
        "dispute_sla.overdue": "overdue",
        "dispute_sla.due_soon": "due soon",
        "concentration_alert.subject": "Concentration alert: {scope}",
        "concentration_alert.body": (
            "{share} of engagements in {scope} over the monitoring window went to "
            "repeat workers, above the {threshold} threshold. Review the governance "
            "dashboard and the first-shot panels."
        ),
        "offer_declined.subject": "{worker} declined the offer on {project}",
        "offer_declined.body": (
            "{worker} declined the engagement offer on {project}.\n\n"
            "Reason: {reason}\nNote: {note}\n\n"
            "The contract will not go ahead. You can offer the work to another "
            "candidate from the project's staffing page."
        ),
        "offer_declined.body.esign": (
            "{worker} declined the contract for {project} at the e-signature provider. "
            "No reason was given. You can offer the work to another candidate from the "
            "project's staffing page."
        ),
        "offer_declined.no_note": "(none)",
        "decline_reason.rate": "Rate",
        "decline_reason.dates": "Dates",
        "decline_reason.scope": "Scope of work",
        "decline_reason.availability": "Availability",
        "decline_reason.other": "Other",
    },
    "fr": {
        "magic_link.subject": "Votre lien de connexion Bonarda",
        "magic_link.body": (
            "Utilisez ce lien pour vous connecter à votre passeport Bonarda. "
            "Il ne fonctionne qu'une fois et expire dans {minutes} minutes :\n\n{link}\n\n"
            "Si vous ne l'avez pas demandé, ignorez cet e-mail."
        ),
        "invitation.subject": "Vous êtes invité(e) sur Bonarda Works",
        "invitation.body": (
            "Bonarda Works a créé un passeport pour vous. Utilisez ce lien pour vous "
            "connecter et compléter votre profil. Il ne fonctionne qu'une fois et expire "
            "dans {minutes} minutes :\n\n{link}\n\n"
            "S'il a expiré, demandez un nouveau lien sur {sign_in_url}."
        ),
        "engagement_confirmed.subject": "Votre mission sur {project} a commencé",
        "engagement_confirmed.body": (
            "Votre contrat pour {project} est signé et votre mission est active à partir "
            "du {start_date}. Vous la retrouvez dans votre passeport Bonarda."
        ),
        "feedback_due.subject": "Retour attendu pour {worker} sur {project}",
        "feedback_due.body": (
            "La mission de {worker} sur {project} est terminée. Merci de soumettre votre "
            "retour : c'est ainsi que son statut reflète son travail."
        ),
        "standing_changed.subject": "Votre statut Bonarda a changé",
        "standing_changed.body": (
            "Votre statut est passé de {previous} à {tier}. Votre passeport présente les "
            "signaux et la politique qui l'expliquent. Si vous pensez qu'il est erroné, "
            "vous pouvez le contester depuis votre passeport."
        ),
        "tier.unrated": "Non classé",
        "tier.tier_1": "Niveau 1",
        "tier.tier_2": "Niveau 2",
        "dispute_resolved.subject": "Votre contestation a été traitée",
        "dispute_resolved.body.upheld": (
            "L'équipe People Ops a donné raison à votre contestation.\n\n"
            "Ses remarques :\n{notes}"
        ),
        "dispute_resolved.body.rejected": (
            "L'équipe People Ops a examiné votre contestation et ne l'a pas retenue.\n\n"
            "Ses remarques :\n{notes}"
        ),
        "dispute_sla.subject": "Contestations : {overdue} en retard, {due_soon} bientôt dues",
        "dispute_sla.body": "Ces contestations ouvertes attendent une décision :\n\n{lines}",
        "dispute_sla.overdue": "en retard",
        "dispute_sla.due_soon": "bientôt due",
        "concentration_alert.subject": "Alerte de concentration : {scope}",
        "concentration_alert.body": (
            "{share} des missions dans {scope} sur la période suivie sont allées à des "
            "personnes déjà engagées plusieurs fois, au-dessus du seuil de {threshold}. "
            "Consultez le tableau de gouvernance et les panneaux de première chance."
        ),
        "offer_declined.subject": "{worker} a refusé l'offre pour {project}",
        "offer_declined.body": (
            "{worker} a refusé l'offre d'engagement pour {project}.\n\n"
            "Motif : {reason}\nNote : {note}\n\n"
            "Le contrat n'ira pas plus loin. Vous pouvez proposer la mission à un autre "
            "candidat depuis la page de staffing du projet."
        ),
        "offer_declined.body.esign": (
            "{worker} a refusé le contrat pour {project} chez le prestataire de signature "
            "électronique. Aucun motif n'a été donné. Vous pouvez proposer la mission à un "
            "autre candidat depuis la page de staffing du projet."
        ),
        "offer_declined.no_note": "(aucune)",
        "decline_reason.rate": "Tarif",
        "decline_reason.dates": "Dates",
        "decline_reason.scope": "Périmètre",
        "decline_reason.availability": "Disponibilité",
        "decline_reason.other": "Autre",
    },
}
DEFAULT_LOCALE = "en"


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    catalog = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = catalog.get(key, MESSAGES[DEFAULT_LOCALE][key])
    return template.format(**params)
