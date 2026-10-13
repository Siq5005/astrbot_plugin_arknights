"""Persistent cache of Skland item bodies.

Every poll re-reads the whole 72-hour window, so fetching one detail per item
per poll would mean roughly 1440 upstream requests a day. Each body is fetched
once ever and remembered here, keeping the extra load near one request per new
post (~3/day).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class DetailStore:
    """Persistent body-text cache keyed by Skland item id.

    The store is a small JSON object mapping item id to body text, written
    atomically with owner-only permissions (mirroring ``core/store.py``).
    """

    def __init__(self, path: Path) -> None:
        """Initialize the store and load any previously cached bodies.

        Args:
            path: State file backing the cache.
        """
        self.path = Path(path)
        self._bodies: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        """(Re)read the store from disk.

        A missing, unreadable or corrupt file yields an empty store. This never
        raises, so state-file trouble cannot break the service.
        """
        self._bodies = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for item_id, text in data.items():
            if isinstance(text, str):
                self._bodies[str(item_id)] = text

    def get(self, item_id: str) -> str | None:
        """Return the cached body for an item, or ``None`` when unknown.

        Args:
            item_id: Skland item id.

        Returns:
            Cached body text, or ``None`` when the id was never fetched.
        """
        return self._bodies.get(str(item_id))

    def put(self, item_id: str, text: str) -> None:
        """Remember an item's body text.

        Args:
            item_id: Skland item id.
            text: Body text.
        """
        self._bodies[str(item_id)] = str(text)

    def prune(self, keep_ids: set[str]) -> None:
        """Drop bodies whose ids are no longer in the polled window.

        Args:
            keep_ids: Item ids to retain.
        """
        keep = {str(item_id) for item_id in keep_ids}
        self._bodies = {
            item_id: text for item_id, text in self._bodies.items() if item_id in keep
        }

    def save(self) -> None:
        """Atomically persist the store with owner-only permissions.

        A failed write is logged and ignored: the in-memory cache still serves
        this process, and a later run simply re-fetches the missing bodies.
        """
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(self._bodies, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("failed to save detail store %s: %s", path, exc)
