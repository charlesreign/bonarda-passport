from datetime import UTC, datetime


def utcnow() -> datetime:
    """The only clock the application uses — always timezone-aware UTC."""
    return datetime.now(UTC)
