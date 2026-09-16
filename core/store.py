"""Persistent storage for account bindings and subscriptions.

Bound credentials are written to a single JSON file inside AstrBot's plugin
data directory with ``0600`` permissions. The file is small enough to be read
and rewritten on every operation, which keeps concurrent writers safe without
holding a long-lived in-memory copy.

This module deliberately avoids importing ``astrbot`` at import time so the
storage layer can be unit tested without the framework installed.
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


def _default_path() -> Path:
    """Resolve the store path inside AstrBot's plugin data directory.

    Returns:
        Absolute path to the bindings JSON file.
    """
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

    return Path(get_astrbot_plugin_data_path()) / PLUGIN_DIR_NAME / "users.json"


def _empty() -> dict[str, Any]:
    """Return a freshly initialized store structure."""
    return {"users": {}, "subs": {"sanity": [], "sign_groups": [], "announce": []}}


class Store:
    """Binding and subscription storage backed by a JSON file."""

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
        """Read and normalize the store from disk.

        A missing, unreadable or corrupt file is treated as an empty store so a
        damaged file never makes the plugin unusable.

        Returns:
            Normalized store dictionary.
        """
        path = self._resolve_path()
        if not path.exists():
            return _empty()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to read %s (%s); starting from empty store", path, exc
            )
            return _empty()
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("users", {})
        subs = data.setdefault("subs", {})
        subs.setdefault("sanity", [])
        subs.setdefault("sign_groups", [])
        subs.setdefault("announce", [])
        return data

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically persist the store with owner-only permissions.

        Args:
            data: Store dictionary to serialize.
        """
        path = self._resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    async def get_user(self, user_key: str) -> dict[str, Any] | None:
        """Return one user's binding record.

        Args:
            user_key: Platform user identifier.

        Returns:
            The user record, or ``None`` when the user has no binding.
        """
        async with self._lock:
            return self._read()["users"].get(str(user_key))

    async def all_users(self) -> dict[str, Any]:
        """Return every binding record keyed by user key."""
        async with self._lock:
            return dict(self._read()["users"])

    async def upsert_auth(
        self,
        user_key: str,
        token: str,
        skland_nickname: str,
        bindings: list[dict[str, Any]],
        umo: str = "",
    ) -> None:
        """Store a freshly authenticated account and its game bindings.

        An existing ``primary_uid`` is preserved when it is still present in the
        new binding list; otherwise the first binding becomes primary.

        Args:
            user_key: Platform user identifier.
            token: Hypergryph passport token.
            skland_nickname: Display name reported by Skland.
            bindings: Binding entries, each containing at least a ``uid``.
            umo: Unified message origin of the private session that bound the
                account, used later for proactive notifications.
        """
        user_key = str(user_key)
        async with self._lock:
            data = self._read()
            users = data["users"]
            existing = users.get(user_key) or {}
            uids = [str(item.get("uid", "")) for item in bindings]
            primary = str(existing.get("primary_uid") or "")
            if primary not in uids:
                primary = uids[0] if uids else ""
            now = int(time.time())
            users[user_key] = {
                "token": token,
                "skland_nickname": skland_nickname,
                "bindings": list(bindings),
                "primary_uid": primary,
                "umo": umo or existing.get("umo") or "",
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
            self._write(data)

    async def set_primary(self, user_key: str, uid: str) -> bool:
        """Switch the primary binding of a user.

        Args:
            user_key: Platform user identifier.
            uid: Binding uid to make primary.

        Returns:
            ``True`` when the binding exists and was switched.
        """
        user_key, uid = str(user_key), str(uid)
        async with self._lock:
            data = self._read()
            user = data["users"].get(user_key)
            if not user:
                return False
            if uid not in [str(item.get("uid", "")) for item in user["bindings"]]:
                return False
            user["primary_uid"] = uid
            self._write(data)
            return True

    async def delete_binding(self, user_key: str, uid: str) -> bool:
        """Remove one binding, dropping the user when no binding remains.

        Args:
            user_key: Platform user identifier.
            uid: Binding uid to remove.

        Returns:
            ``True`` when a binding was removed.
        """
        user_key, uid = str(user_key), str(uid)
        async with self._lock:
            data = self._read()
            user = data["users"].get(user_key)
            if not user:
                return False
            remain = [b for b in user["bindings"] if str(b.get("uid", "")) != uid]
            if len(remain) == len(user["bindings"]):
                return False
            if not remain:
                self._drop_user(data, user_key)
            else:
                user["bindings"] = remain
                if str(user.get("primary_uid")) == uid:
                    user["primary_uid"] = str(remain[0].get("uid", ""))
            self._write(data)
            return True

    async def remove_user(self, user_key: str) -> bool:
        """Remove a user entirely and clear their subscriptions.

        Args:
            user_key: Platform user identifier.

        Returns:
            ``True`` when the user existed.
        """
        user_key = str(user_key)
        async with self._lock:
            data = self._read()
            if user_key not in data["users"]:
                return False
            self._drop_user(data, user_key)
            self._write(data)
            return True

    @staticmethod
    def _drop_user(data: dict[str, Any], user_key: str) -> None:
        """Delete a user record and any per-user subscription entries."""
        data["users"].pop(user_key, None)
        for key in ("sanity", "announce"):
            data["subs"][key] = [
                item
                for item in data["subs"][key]
                if str(item.get("user_key", "")) != user_key
            ]

    async def list_sanity_subs(self) -> list[dict[str, str]]:
        """Return the sanity-full notification targets.

        Returns:
            One entry per subscriber with ``user_key`` and ``umo``.
        """
        async with self._lock:
            return [dict(item) for item in self._read()["subs"]["sanity"]]

    async def set_sanity_sub(self, user_key: str, umo: str, enabled: bool) -> None:
        """Enable or disable sanity-full notifications for a user.

        Args:
            user_key: Platform user identifier.
            umo: Session to notify; required when enabling.
            enabled: Desired subscription state.
        """
        user_key = str(user_key)
        async with self._lock:
            data = self._read()
            subs = [
                item
                for item in data["subs"]["sanity"]
                if str(item.get("user_key", "")) != user_key
            ]
            if enabled:
                subs.append({"user_key": user_key, "umo": str(umo)})
            data["subs"]["sanity"] = subs
            self._write(data)

    async def list_sign_groups(self) -> list[dict[str, str]]:
        """Return the group notification targets for automatic sign-in.

        Returns:
            One entry per group with ``group_id`` and ``umo``.
        """
        async with self._lock:
            return [dict(item) for item in self._read()["subs"]["sign_groups"]]

    async def set_sign_group(self, group_id: str, umo: str, enabled: bool) -> None:
        """Enable or disable sign-in notifications for a group.

        Args:
            group_id: Platform group identifier.
            umo: Group session to notify; required when enabling.
            enabled: Desired subscription state.
        """
        group_id = str(group_id)
        async with self._lock:
            data = self._read()
            groups = [
                item
                for item in data["subs"]["sign_groups"]
                if str(item.get("group_id", "")) != group_id
            ]
            if enabled:
                groups.append({"group_id": group_id, "umo": str(umo)})
            data["subs"]["sign_groups"] = groups
            self._write(data)

    async def list_announce_subs(self) -> list[dict[str, str]]:
        """Return the announcement notification targets.

        Returns:
            One entry per subscriber with ``user_key`` and ``umo``.
        """
        async with self._lock:
            return [dict(item) for item in self._read()["subs"]["announce"]]

    async def set_announce_sub(self, user_key: str, umo: str, enabled: bool) -> None:
        """Enable or disable announcement notifications for a user.

        Args:
            user_key: Platform user identifier.
            umo: Session to notify; required when enabling.
            enabled: Desired subscription state.
        """
        user_key = str(user_key)
        async with self._lock:
            data = self._read()
            subs = [
                item
                for item in data["subs"]["announce"]
                if str(item.get("user_key", "")) != user_key
            ]
            if enabled:
                subs.append({"user_key": user_key, "umo": str(umo)})
            data["subs"]["announce"] = subs
            self._write(data)
