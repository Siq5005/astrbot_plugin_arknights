"""Hold the newest official feed in memory and refresh it in the background.

Every plugin instance talks to this service instead of to Skland, so the number
of upstream requests stays constant no matter how many users install the plugin.
A failed refresh keeps the previous payload: a stale answer beats no answer, and
``last_success_at`` lets the caller decide when stale is too stale.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .settings import Settings

logger = logging.getLogger(__name__)

Fetcher = Callable[[], Awaitable[list[dict[str, Any]]]]


class FeedCache:
    """In-memory cache of the official feed."""

    def __init__(self, settings: Settings, fetcher: Fetcher | None = None) -> None:
        """Initialize the cache.

        Args:
            settings: Service settings.
            fetcher: Coroutine producing fresh records; injected by tests.
        """
        self.settings = settings
        self._fetcher = fetcher
        self._items: list[dict[str, Any]] = []
        self._last_success_at = 0
        self._last_error = ""

    def items(self) -> list[dict[str, Any]]:
        """Return the cached records.

        Returns:
            The current record list, newest first.
        """
        return list(self._items)

    def is_stale(self, now: int | None = None) -> bool:
        """Report whether the cache is older than the configured limit.

        Args:
            now: Unix seconds to compare against; defaults to the clock.

        Returns:
            ``True`` when never refreshed or past ``stale_minutes``.
        """
        if self._last_success_at <= 0:
            return True
        reference = int(now if now is not None else time.time())
        return reference - self._last_success_at > self.settings.stale_minutes * 60

    def snapshot(self) -> dict[str, Any]:
        """Describe the cache for the HTTP layer.

        Returns:
            Mapping with ``items``, ``last_success_at``, ``last_error`` and
            ``stale``.
        """
        return {
            "items": self.items(),
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "stale": self.is_stale(),
        }

    async def refresh(self) -> bool:
        """Fetch fresh records.

        Returns:
            ``True`` when the refresh succeeded, ``False`` otherwise. The
            previous payload is preserved on failure.
        """
        fetcher = self._fetcher
        if fetcher is None:
            return False
        try:
            records = await fetcher()
        except Exception as exc:  # noqa: BLE001 - reported through the endpoint
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("feed refresh failed: %s", self._last_error)
            return False

        self._items = list(records)
        self._last_success_at = int(time.time())
        self._last_error = ""
        logger.info("feed refreshed: %d items", len(self._items))
        return True

    async def run_forever(self) -> None:
        """Refresh on a fixed interval until cancelled."""
        while True:
            await self.refresh()
            await asyncio.sleep(self.settings.poll_interval_seconds)
