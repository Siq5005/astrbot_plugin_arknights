"""FastAPI surface of the aggregator.

Two endpoints: ``/api/ark/v1/feed`` for the plugin (API-key gated) and
``/api/ark/v1/health`` for monitoring (open, exposes no content).
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from .cache import FeedCache
from .credentials import load_user_token
from .details import DetailStore
from .feed import fetch_official
from .settings import Settings
from .skland_client import SklandClient

Fetcher = Any


def build_fetcher(settings: Settings) -> Any:
    """Create the coroutine used to refresh the cache.

    Args:
        settings: Service settings.

    Returns:
        An async callable returning normalised records.

    Raises:
        RuntimeError: When no passport token has been provisioned yet.
    """

    try:
        details = DetailStore(settings.state_file)
    except Exception:  # noqa: BLE001 - state-file trouble must not break the feed
        details = None

    async def fetcher() -> list[dict[str, Any]]:
        token = load_user_token(settings.credential_file)
        if not token:
            raise RuntimeError("尚未登录：请先运行 scripts/login.py 扫码获取凭证")
        client = SklandClient()
        try:
            return await fetch_official(
                client, token, window_hours=settings.window_hours, details=details
            )
        finally:
            await client.close()

    return fetcher


def create_app(
    settings: Settings | None = None,
    cache: FeedCache | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Service settings; read from the environment when omitted.
        cache: Pre-built cache, used by tests.

    Returns:
        The configured application.
    """
    resolved = settings or Settings.from_env()
    feed_cache = cache or FeedCache(resolved, fetcher=build_fetcher(resolved))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(feed_cache.run_forever())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="arksource", version="1.0.0", lifespan=lifespan)
    app.state.cache = feed_cache
    app.state.settings = resolved

    @app.get("/api/ark/v1/health")
    async def health() -> dict[str, Any]:
        """Report cache freshness without exposing content."""
        snapshot = feed_cache.snapshot()
        return {
            "code": 0,
            "data": {
                "stale": snapshot["stale"],
                "count": len(snapshot["items"]),
                "last_success_at": snapshot["last_success_at"],
                "last_error": snapshot["last_error"],
            },
        }

    @app.get("/api/ark/v1/feed")
    async def feed(x_api_key: str = Header(default="")):
        """Return the normalised official feed."""
        expected = resolved.api_key
        if not expected or not secrets.compare_digest(x_api_key, expected):
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "缺少或无效的 X-API-Key"},
            )
        snapshot = feed_cache.snapshot()
        return {
            "code": 0,
            "data": {
                "items": snapshot["items"],
                "stale": snapshot["stale"],
                "last_success_at": snapshot["last_success_at"],
                "last_error": snapshot["last_error"],
            },
        }

    return app


app = create_app()
