"""The HTTP surface: API-key gate plus a stable response envelope."""

import httpx
import pytest
from app.cache import FeedCache
from app.main import create_app
from app.settings import Settings


def _settings(**overrides):
    base = dict(
        api_key="secret",
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


def _client(cache, settings):
    app = create_app(settings=settings, cache=cache)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_feed_requires_api_key():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed")

    assert response.status_code == 401
    assert response.json()["code"] == 401


@pytest.mark.anyio
async def test_feed_rejects_wrong_api_key():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed", headers={"X-API-Key": "nope"})

    assert response.status_code == 401


@pytest.mark.anyio
async def test_feed_returns_items_with_valid_key():
    async def fetcher():
        return [{"id": "1", "title": "t", "published_at": 100}]

    cache = FeedCache(_settings(), fetcher=fetcher)
    await cache.refresh()
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["items"] == [{"id": "1", "title": "t", "published_at": 100}]
    assert body["data"]["stale"] is False


@pytest.mark.anyio
async def test_health_is_not_gated_and_reports_staleness():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/health")

    assert response.status_code == 200
    assert response.json()["data"]["stale"] is True


@pytest.mark.anyio
async def test_feed_rejects_when_no_key_is_configured():
    """An unconfigured service must never accept a request."""

    async def fetcher():
        return []

    blank = _settings(api_key="")
    cache = FeedCache(blank, fetcher=fetcher)
    async with _client(cache, blank) as client:
        response = await client.get("/api/ark/v1/feed", headers={"X-API-Key": ""})

    assert response.status_code == 401
