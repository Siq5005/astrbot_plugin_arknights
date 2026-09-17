"""Game data tables used by the gacha analysis.

Two sources are merged, because neither carries everything:

* ``yuanyan3060/ArknightsGameResource`` provides structured pool metadata
  (name, open/end time, rule type) but stores the pool description as text.
* ``weedy.prts.wiki`` provides the structured UP-character lists.

Both downloads are cached on disk and refreshed after a TTL, so the analysis
keeps working when a mirror is briefly unreachable.

This module imports only the framework logger from ``astrbot``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from astrbot.api import logger

# Ordered by preference; the first reachable mirror wins.
META_URLS = (
    "https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/gamedata/excel/gacha_table.json",
    "https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/gamedata/excel/gacha_table.json",
)
UP_URLS = ("https://weedy.prts.wiki/gacha_table.json",)

DEFAULT_TTL_SECONDS = 86_400

# The UP table reports ``rarityRank`` zero based, so 5 means six star.
SIX_STAR_RARITY = 5
FIVE_STAR_RARITY = 4


class GameData:
    """Cached gacha pool metadata and UP-character tables."""

    def __init__(
        self,
        cache_dir: Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the store.

        Args:
            cache_dir: Directory used for the downloaded tables.
            ttl_seconds: How long a cached table stays valid.
            client: Optional pre-built HTTP client, used by tests.
        """
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._owns_client = client is None
        self.pool_meta: dict[str, dict[str, Any]] = {}
        self.pool_up: dict[str, dict[str, list[str]]] = {}
        self.loaded_at = 0.0

    async def close(self) -> None:
        """Release the HTTP client when this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
            self._owns_client = True
        return self._client

    def _cache_file(self, name: str) -> Path:
        """Return the cache path for a table."""
        return self.cache_dir / name

    def _read_cache(self, name: str) -> Any | None:
        """Read a cached table when it is still fresh.

        Args:
            name: Cache file name.

        Returns:
            Parsed JSON, or ``None`` when missing, stale or corrupt.
        """
        path = self._cache_file(name)
        try:
            if not path.is_file():
                return None
            if time.time() - path.stat().st_mtime > self.ttl_seconds:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("读取缓存 %s 失败: %s", path, exc)
            return None

    def _write_cache(self, name: str, payload: Any) -> None:
        """Persist a table, ignoring write failures."""
        path = self._cache_file(name)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("写入缓存 %s 失败: %s", path, exc)

    async def _fetch_json(self, urls: tuple[str, ...], name: str) -> Any | None:
        """Download a table, trying each mirror in order.

        Args:
            urls: Candidate URLs.
            name: Cache file name for the payload.

        Returns:
            Parsed JSON, or ``None`` when every mirror failed.
        """
        cached = self._read_cache(name)
        if cached is not None:
            return cached
        client = self._get_client()
        for url in urls:
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("下载 %s 失败: %s", url, exc)
                continue
            self._write_cache(name, payload)
            return payload
        return None

    async def ensure(self, force: bool = False) -> bool:
        """Load both tables, refreshing them when stale.

        Args:
            force: Ignore any cached copy.

        Returns:
            ``True`` when pool metadata is available. UP data is optional, so a
            failure there still returns ``True`` with empty UP lists.
        """
        if (
            not force
            and self.pool_meta
            and time.time() - self.loaded_at < self.ttl_seconds
        ):
            return True

        if force:
            for name in ("gacha_meta.json", "gacha_up.json"):
                try:
                    self._cache_file(name).unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug("删除缓存 %s 失败: %s", name, exc)

        meta_payload = await self._fetch_json(META_URLS, "gacha_meta.json")
        if not isinstance(meta_payload, dict):
            return False
        self.pool_meta = self._parse_meta(meta_payload)

        up_payload = await self._fetch_json(UP_URLS, "gacha_up.json")
        self.pool_up = self._parse_up(up_payload) if up_payload else {}
        self.loaded_at = time.time()
        logger.info(
            "卡池数据已加载：%d 个卡池，%d 个池含 UP 详情",
            len(self.pool_meta),
            len(self.pool_up),
        )
        return True

    @staticmethod
    def _parse_meta(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Extract pool metadata from the resource table.

        Args:
            payload: Parsed ``gacha_table.json``.

        Returns:
            Mapping of pool id to name, rule type and time window.
        """
        result: dict[str, dict[str, Any]] = {}
        for item in payload.get("gachaPoolClient") or []:
            pool_id = str(item.get("gachaPoolId") or "")
            if not pool_id:
                continue
            result[pool_id] = {
                "name": str(item.get("gachaPoolName") or ""),
                "rule_type": int(item.get("gachaRuleType") or 0),
                "open_time": int(item.get("openTime") or 0),
                "end_time": int(item.get("endTime") or 0),
            }
        return result

    @staticmethod
    def _parse_up(payload: Any) -> dict[str, dict[str, list[str]]]:
        """Extract the rate-up character lists from the PRTS table.

        Only ``upCharInfo`` describes rate-up. ``availCharInfo`` lists every
        character obtainable from the pool (a normal banner advertises ten or
        more six stars there), so treating it as rate-up made every pull look
        like an UP hit and silently zeroed the off-rate — most visibly on the
        special banners that carry no ``upCharInfo`` at all. Pools without
        ``upCharInfo`` are therefore reported as having no UP data, and the
        analysis skips their UP judgement instead of inventing one.

        Args:
            payload: Parsed PRTS ``gacha_table.json``.

        Returns:
            Mapping of pool id to ``{"six": [...], "five": [...]}``. Pools with
            no rate-up data are omitted.
        """
        if isinstance(payload, list):
            pools = payload
        elif isinstance(payload, dict):
            pools = payload.get("gachaPoolClient")
        else:
            return {}
        result: dict[str, dict[str, list[str]]] = {}
        for item in pools or []:
            if not isinstance(item, dict):
                continue
            pool_id = str(item.get("gachaPoolId") or "")
            if not pool_id:
                continue
            detail = item.get("gachaPoolDetail")
            detail = detail if isinstance(detail, dict) else {}
            info = detail.get("detailInfo") or {}
            six: list[str] = []
            five: list[str] = []
            # A single entry may carry several characters (joint banners list
            # three or more six stars in one entry), so collect every entry
            # rather than only the first.
            for entry in (info.get("upCharInfo") or {}).get("perCharList") or []:
                if not isinstance(entry, dict):
                    continue
                rank = entry.get("rarityRank")
                chars = [str(c) for c in entry.get("charIdList") or []]
                if rank == SIX_STAR_RARITY:
                    six.extend(chars)
                elif rank == FIVE_STAR_RARITY:
                    five.extend(chars)
            if six or five:
                result[pool_id] = {"six": six, "five": five}
        return result

    def pool_name(self, pool_id: str) -> str:
        """Return a readable pool name.

        Args:
            pool_id: Pool identifier from the gacha record.

        Returns:
            The pool name, or the raw id when unknown.
        """
        return str((self.pool_meta.get(pool_id) or {}).get("name") or pool_id)

    def up_six(self, pool_id: str) -> list[str]:
        """Return the UP six-star operator ids for a pool."""
        return list((self.pool_up.get(pool_id) or {}).get("six") or [])


# Banner families are recognised from the pool id prefix. The prefixes below
# were read straight out of the live table, so the grouping does not depend on
# guessing what each ``gachaRuleType`` number means. Order matters: the most
# specific prefix must be tested first.
BANNER_GROUPS: tuple[tuple[str, str], ...] = (
    ("CLASSIC_DOUBLE_", "中坚双UP寻访"),
    ("CLASSIC_ATTAIN_", "中坚跨年欢庆"),
    ("FESCLASSIC_", "中坚FES寻访"),
    ("CLASSIC_", "中坚寻访"),
    ("LIMITED_", "限定寻访"),
    ("LINKAGE_", "联动寻访"),
    ("ATTAIN_", "跨年欢庆寻访"),
    ("SINGLE_", "单UP寻访"),
    ("DOUBLE_", "双UP寻访"),
    ("SPECIAL_", "定向甄选"),
    ("RETURN_", "归航寻访"),
    ("NORM_", "标准寻访"),
)

UNKNOWN_BANNER_LABEL = "其他寻访"


def banner_group(pool_id: str) -> tuple[str, str]:
    """Classify a pool into a banner family.

    Pity and the six-star sequence are tracked per banner family in game, so the
    analysis groups records the same way instead of mixing every banner into one
    running total.

    Args:
        pool_id: Pool identifier from a gacha record.

    Returns:
        Tuple of the group key and its display label.
    """
    text = str(pool_id or "")
    for prefix, label in BANNER_GROUPS:
        if text.startswith(prefix):
            return prefix, label
    return "", UNKNOWN_BANNER_LABEL
