import json
from typing import Any
from uuid import uuid4

import pytest
from arq.worker import Retry
from fakeredis import aioredis as fake_aioredis

from app.worker import jobs


@pytest.fixture
def failing_process_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(jobs, "process_event", boom)


@pytest.mark.usefixtures("failing_process_event")
async def test_failed_handler_is_retried_with_backoff() -> None:
    ctx = {"sessionmaker": None, "registry": None, "job_try": 2, "redis": None}

    with pytest.raises(Retry) as excinfo:
        await jobs.run_event_handler(ctx, str(uuid4()), "roster.refresh")

    assert excinfo.value.defer_score == 4_000  # 2 ** job_try seconds, in ms


@pytest.mark.usefixtures("failing_process_event")
async def test_handler_is_dead_lettered_on_final_try() -> None:
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    event_id = str(uuid4())
    ctx = {
        "sessionmaker": None,
        "registry": None,
        "job_try": jobs.MAX_HANDLER_TRIES,
        "redis": redis,
    }

    result = await jobs.run_event_handler(ctx, event_id, "roster.refresh")

    assert result is False
    entry = json.loads((await redis.lrange(jobs.DEAD_LETTER_KEY, 0, -1))[0])
    assert entry["event_id"] == event_id
    assert entry["handler"] == "roster.refresh"
    assert "handler exploded" in entry["error"]
