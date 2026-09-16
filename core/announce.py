"""Official Arknights announcement feed.

Announcements come from the in-game configuration endpoint that the client
itself reads, so no third-party service is involved::

    https://ak-conf.hypergryph.com/config/prod/announce_meta/Android/announcement.meta.json

Each entry carries an id, a two-line title, a category group and a link to the
full HTML announcement. The link embeds a unix timestamp, which is the only
reliable ordering key since the payload itself only exposes day and month.

This module never imports ``astrbot``.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ANNOUNCE_URL = (
    "https://ak-conf.hypergryph.com/config/prod/announce_meta/"
    "Android/announcement.meta.json"
)

GROUP_CN: dict[str, str] = {
    "SYSTEM": "系统",
    "ACTIVITY": "活动",
    "NEWS": "资讯",
}
UNKNOWN_GROUP_CN = "公告"

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TS_RE = re.compile(r"_(\d{10})\.html?$")


class AnnounceError(Exception):
    """Raised when the announcement feed cannot be read."""


def html_to_text(markup: str) -> str:
    """Flatten announcement HTML into readable plain text.

    Args:
        markup: Raw HTML from an announcement page.

    Returns:
        Whitespace-normalized text with block tags turned into newlines.
    """
    text = _BLOCK_RE.sub(" ", str(markup or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<(p|div|li|tr|h[1-6])[^>]*>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def normalize(
    item: dict[str, Any], group_cn: dict[str, str] | None = None
) -> dict[str, Any]:
    """Normalize one raw announcement entry.

    Args:
        item: Entry from ``announceList``.
        group_cn: Optional group label overrides.

    Returns:
        Record with a cleaned title, category label and derived timestamp.
    """
    group_cn = GROUP_CN if group_cn is None else group_cn
    url = str(item.get("webUrl") or "")
    match = _TS_RE.search(url)
    stamp = int(match.group(1)) if match else 0
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
    group = str(item.get("group") or "")
    date_text = ""
    if stamp:
        try:
            date_text = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            date_text = ""
    if not date_text and item.get("month") and item.get("day"):
        date_text = f"{int(item['month']):02d}-{int(item['day']):02d}"
    return {
        "id": str(item.get("announceId") or ""),
        "title": title,
        "group": group,
        "group_cn": group_cn.get(group, UNKNOWN_GROUP_CN),
        "url": url,
        "ts": stamp,
        "date_text": date_text,
    }


class AnnounceClient:
    """Reads the official announcement feed."""

    def __init__(
        self, url: str = ANNOUNCE_URL, client: httpx.AsyncClient | None = None
    ) -> None:
        """Initialize the client.

        Args:
            url: Announcement metadata endpoint.
            client: Optional pre-built HTTP client, used by tests.
        """
        self.url = url
        self._client = client
        self._owns_client = client is None

    async def close(self) -> None:
        """Release the HTTP client when this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=25.0)
            self._owns_client = True
        return self._client

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch and normalize the announcement list.

        Returns:
            Announcements sorted newest first.

        Raises:
            AnnounceError: When the feed is unreachable or malformed.
        """
        try:
            response = await self._get_client().get(self.url)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise AnnounceError(f"公告获取失败: {exc}") from exc
        except ValueError as exc:
            raise AnnounceError("公告响应格式异常") from exc
        if not isinstance(payload, dict):
            raise AnnounceError("公告响应格式异常")
        records = [
            normalize(item, GROUP_CN)
            for item in payload.get("announceList") or []
            if isinstance(item, dict)
        ]
        records = [record for record in records if record["id"]]
        records.sort(
            key=lambda record: (record["ts"], int(record["id"] or 0)), reverse=True
        )
        return records

    async def focus_id(self) -> str:
        """Return the featured announcement id.

        Returns:
            The id, or an empty string when unavailable.
        """
        try:
            response = await self._get_client().get(self.url)
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("focusAnnounceId") or "")

    async def detail(self, url: str, limit: int = 1200) -> str:
        """Fetch an announcement page and flatten it to text.

        Args:
            url: Announcement page URL.
            limit: Maximum number of characters to return.

        Returns:
            Plain text, truncated to ``limit`` characters.

        Raises:
            AnnounceError: When the page is unreachable.
        """
        if not url:
            raise AnnounceError("公告链接为空")
        try:
            response = await self._get_client().get(url)
            response.raise_for_status()
            markup = response.text
        except httpx.HTTPError as exc:
            raise AnnounceError(f"公告正文获取失败: {exc}") from exc
        text = html_to_text(markup)
        return text[:limit]
