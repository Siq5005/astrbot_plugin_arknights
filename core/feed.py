"""Self-hosted Arknights official feed (森空岛「官方」栏目).

The aggregator behind this client holds a single Skland credential, so plugin
users need no Hypergryph account of their own. Records are normalised into the
exact shape :meth:`core.announce.AnnounceClient.fetch` returns, which lets the
push job, the renderer and the templates stay source-agnostic.
"""

from __future__ import annotations

import html as html_module
from datetime import datetime
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://ark.youyou.ink/api/ark/v1"
FEED_PATH = "/feed"
GROUP_CN = "官方"
GROUP_KEY = "OFFICIAL"


class FeedError(Exception):
    """Raised when the self-hosted feed cannot be read."""


def _format_time(stamp: Any) -> str:
    """Render a unix timestamp the way the website source does.

    Args:
        stamp: Unix seconds.

    Returns:
        ``YYYY-MM-DD HH:MM``, or an empty string when unparsable.
    """
    try:
        return datetime.fromtimestamp(int(stamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _body_html(text: str, images: list[str]) -> str:
    """Build the card body from plain text plus images.

    Args:
        text: Body text from the aggregator.
        images: Image URLs, cover first.

    Returns:
        HTML fragment understood by ``announce_detail.html``.
    """
    parts: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            parts.append(f"<p>{html_module.escape(line)}</p>")
    for url in images:
        parts.append(f'<img src="{html_module.escape(url, quote=True)}" />')
    return "".join(parts)


class FeedClient:
    """Reads the self-hosted official feed."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Aggregator base URL, without the trailing ``/feed``.
            api_key: Value sent as ``X-API-Key``.
            client: Optional pre-built HTTP client, used by tests.
        """
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
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
            self._client = httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot-Arknights)"},
            )
            self._owns_client = True
        return self._client

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch the official feed.

        Returns:
            Records newest first, in the website source's shape.

        Raises:
            FeedError: On transport failure, a non-2xx status, a non-zero
                business code, or a malformed payload.
        """
        url = f"{self.base_url}{FEED_PATH}"
        try:
            response = await self._get_client().get(
                url, headers={"X-API-Key": self.api_key}
            )
        except httpx.HTTPError as exc:
            raise FeedError(f"自建源请求失败: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise FeedError(f"自建源响应格式异常: HTTP {response.status_code}") from exc

        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or "")
        if response.status_code >= 400:
            raise FeedError(message or f"自建源请求失败: HTTP {response.status_code}")
        if not isinstance(payload, dict) or payload.get("code") not in (0, None):
            raise FeedError(message or "自建源返回错误")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise FeedError("自建源响应缺少 data")
        items = data.get("items")
        if not isinstance(items, list):
            raise FeedError("自建源响应缺少 items")
        stale = bool(data.get("stale"))

        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            # Upstream may change field types without warning. Coerce them here
            # so a single odd record cannot leak a raw ValueError/TypeError:
            # the caller only degrades on FeedError.
            try:
                stamp = int(item.get("published_at") or 0)
            except (TypeError, ValueError):
                stamp = 0
            try:
                kind = int(item.get("kind") or 0)
            except (TypeError, ValueError):
                kind = 0
            raw_images = item.get("images")
            if not isinstance(raw_images, list):
                raw_images = []
            images = [str(u) for u in raw_images if u]
            cover = str(item.get("cover") or "")
            ordered = ([cover] if cover else []) + [u for u in images if u != cover]
            text = str(item.get("text") or "")
            records.append(
                {
                    "id": item_id,
                    "title": str(item.get("title") or item_id),
                    "author": "明日方舟",
                    "brief": text,
                    "group": GROUP_KEY,
                    "group_cn": GROUP_CN,
                    "url": str(item.get("url") or ""),
                    "ts": stamp,
                    "date_text": _format_time(stamp),
                    "text": text,
                    "images": ordered,
                    "image_total": len(ordered),
                    "body_html": _body_html(text, ordered),
                    "kind": kind,
                    "cover": cover,
                    "stale": stale,
                }
            )

        records.sort(key=lambda entry: (entry["ts"], entry["id"]), reverse=True)
        return records
