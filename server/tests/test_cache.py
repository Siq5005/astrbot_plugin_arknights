"""The cache must survive upstream failures without losing its last good payload."""

import pytest
from app.cache import FeedCache
from app.settings import Settings


def _settings(**overrides):
    base = dict(
        api_key="k",
        credential_file="/tmp/c.json",
        state_file="/tmp/s.json",
        host="127.0.0.1",
        port=8788,
        poll_interval_seconds=600,
        window_hours=72,
        stale_minutes=60,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.mark.anyio
async def test_refresh_stores_items_and_timestamp():
    async def fetcher():
        return [{"id": "1", "title": "t"}]

    cache = FeedCache(_settings(), fetcher=fetcher)

    assert await cache.refresh() is True
    snapshot = cache.snapshot()
    assert snapshot["items"] == [{"id": "1", "title": "t"}]
    assert snapshot["last_success_at"] > 0
    assert snapshot["last_error"] == ""


@pytest.mark.anyio
async def test_failed_refresh_keeps_last_good_items_and_records_error():
    calls = {"n": 0}

    async def fetcher():
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"id": "1", "title": "t"}]
        raise RuntimeError("boom")

    cache = FeedCache(_settings(), fetcher=fetcher)

    await cache.refresh()
    assert await cache.refresh() is False

    snapshot = cache.snapshot()
    assert snapshot["items"] == [{"id": "1", "title": "t"}]
    assert "boom" in snapshot["last_error"]
    assert snapshot["last_success_at"] > 0


@pytest.mark.anyio
async def test_is_stale_uses_last_success_age():
    async def fetcher():
        return [{"id": "1"}]

    cache = FeedCache(_settings(stale_minutes=60), fetcher=fetcher)
    await cache.refresh()

    assert cache.is_stale(now=cache.snapshot()["last_success_at"] + 59 * 60) is False
    assert cache.is_stale(now=cache.snapshot()["last_success_at"] + 61 * 60) is True


def test_is_stale_when_never_refreshed():
    cache = FeedCache(_settings(), fetcher=None)

    assert cache.snapshot()["last_success_at"] == 0
    assert cache.is_stale() is True
