"""On-disk storage for headhunting records.

The official history endpoint only returns a recent window, so anything the
plugin sees is kept locally and merged on every sync. History therefore
accumulates across queries instead of being re-fetched and forgotten, and a
later sync never loses an older pull.

This module never imports ``astrbot``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLUGIN_DIR_NAME = "astrbot_plugin_arknights"
STORE_FILE_NAME = "gacha.json"

# A record is unique by the gacha category, its timestamp and its position in
# that page; the same (timestamp, position) pair repeats across categories.
_KEY_FIELDS = ("category", "gachaTs", "pos")


def _default_path() -> Path:
    """Resolve the store path inside AstrBot's plugin data directory.

    Returns:
        Absolute path to the headhunting records JSON file.
    """
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

    return Path(get_astrbot_plugin_data_path()) / PLUGIN_DIR_NAME / STORE_FILE_NAME


def _key(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Build the identity key of a record.

    Args:
        record: One headhunting record.

    Returns:
        Tuple that is unique within an account.
    """
    return tuple(record.get(field) for field in _KEY_FIELDS)  # type: ignore[return-value]


class GachaStore:
    """Headhunting record storage backed by a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the store.

        Args:
            path: Explicit storage path. When ``None`` the AstrBot plugin data
                directory is resolved lazily on first use, which keeps unit
                tests independent from the framework.
        """
        self.path: Path | None = Path(path) if path is not None else None
        self._lock = asyncio.Lock()

    def _resolve_path(self) -> Path:
        """Return the storage path, resolving the framework default if needed."""
        if self.path is None:
            self.path = _default_path()
        return self.path

    def _read(self) -> dict[str, Any]:
        """Read the store, recovering from a corrupt file.

        Returns:
            Store contents with a ``roles`` mapping.
        """
        path = self._resolve_path()
        if not path.exists():
            return {"roles": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("抽卡记录文件损坏，已重置: %s", exc)
            return {"roles": {}}
        if not isinstance(data, dict):
            return {"roles": {}}
        if not isinstance(data.get("roles"), dict):
            data["roles"] = {}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        """Write the store atomically with owner-only permissions.

        Args:
            data: Full store contents.
        """
        path = self._resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    async def load(self, uid: str) -> dict[str, Any]:
        """Return what is stored for one role.

        Args:
            uid: Game role identifier.

        Returns:
            Mapping with ``records`` and ``synced_at``.
        """
        async with self._lock:
            role = self._read()["roles"].get(str(uid)) or {}
        records = role.get("records")
        return {
            "records": records if isinstance(records, list) else [],
            "synced_at": int(role.get("synced_at") or 0),
        }

    async def merge(
        self, uid: str, records: list[dict[str, Any]], synced_at: int | None = None
    ) -> dict[str, Any]:
        """Merge freshly fetched records into the stored history.

        Args:
            uid: Game role identifier.
            records: Records just fetched from the official endpoint.
            synced_at: Sync timestamp; defaults to now.

        Returns:
            The merged history with the updated ``synced_at``.
        """
        stamp = int(synced_at if synced_at is not None else time.time())
        async with self._lock:
            data = self._read()
            role = data["roles"].get(str(uid)) or {}
            known = {
                _key(item): item
                for item in (role.get("records") or [])
                if isinstance(item, dict)
            }
            for item in records:
                if isinstance(item, dict):
                    known[_key(item)] = item
            merged = sorted(
                known.values(),
                key=lambda item: (
                    int(item.get("gachaTs") or 0),
                    int(item.get("pos") or 0),
                ),
            )
            data["roles"][str(uid)] = {"synced_at": stamp, "records": merged}
            self._write(data)
        return {"records": merged, "synced_at": stamp}

    async def clear(self, uid: str) -> None:
        """Drop the stored history of one role.

        Args:
            uid: Game role identifier.
        """
        async with self._lock:
            data = self._read()
            if str(uid) in data["roles"]:
                data["roles"].pop(str(uid), None)
                self._write(data)
