from app.core.outbox.relay import BACKOFF_CAP_SECONDS, BACKOFF_INITIAL_SECONDS, next_backoff


def test_next_backoff_starts_at_the_initial_value() -> None:
    assert next_backoff(0.0) == BACKOFF_INITIAL_SECONDS


def test_next_backoff_doubles_each_consecutive_call() -> None:
    first = next_backoff(0.0)
    second = next_backoff(first)
    third = next_backoff(second)

    assert (first, second, third) == (1.0, 2.0, 4.0)


def test_next_backoff_is_capped() -> None:
    assert next_backoff(BACKOFF_CAP_SECONDS) == BACKOFF_CAP_SECONDS
    assert next_backoff(BACKOFF_CAP_SECONDS / 2 + 1) == BACKOFF_CAP_SECONDS
