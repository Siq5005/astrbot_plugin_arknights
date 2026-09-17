"""Official Arknights announcements.

The in-game ``announce_meta`` file used previously stopped being updated in May
2025 — its ``Last-Modified`` header still says so — so the plugin now reads the
official website instead, which is current:

* ``https://ak.hypergryph.com/news`` renders every announcement group into the
  page itself; ``ANNOUNCEMENT`` / ``ACTIVITY`` / ``NEWS`` are parsed out of the
  embedded payload.
* ``https://ak.hypergryph.com/news/{cid}`` server-renders one announcement,
  including its rich-text body and any inline artwork.

The body is returned as HTML so the caller can render it into a card, which
suits the text-heavy website announcements.

This module imports only the framework logger from ``astrbot``.
"""

from __future__ import annotations

import html as html_module
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx

NEWS_URL = "https://ak.hypergryph.com/news"
DETAIL_URL = "https://ak.hypergryph.com/news/{cid}"

# The site renders the publish date as "2026 // 09 / 11" above the body, which
# is a stable anchor; the surrounding class names are per-build hashes.
DATE_MARKER_RE = re.compile(r"\d{4}\s*//\s*\d{1,2}\s*/\s*\d{1,2}")

# Group keys inside the page payload, in display order. LATEST aggregates the
# others and is skipped so nothing is listed twice.
GROUP_KEYS: tuple[str, ...] = ("ANNOUNCEMENT", "ACTIVITY", "NEWS")
GROUP_CN: dict[str, str] = {
    "ANNOUNCEMENT": "公告",
    "ACTIVITY": "活动",
    "NEWS": "资讯",
}
UNKNOWN_GROUP_CN = "公告"

# The site's ANNOUNCEMENT group is a superset of the others, so its group key
# cannot label an item. Classify from the copy instead: deterministic and it
# produces labels a reader recognises.
_ACTIVITY_MARKERS = ("活动", "寻访", "限时", "庆典", "上架", "复刻", "创作征集", "签到")
_SYSTEM_MARKERS = ("闪断", "维护", "更新公告", "补偿", "说明", "公示", "处理")

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc=[\"']([^\"']+)[\"']", re.I)

# One entry of the embedded payload, matched field by field so a malformed
# neighbour cannot swallow the rest of the list.
_ITEM_RE = re.compile(
    r'\{\\"cid\\":\\"(\d+)\\".*?'
    r'\\"displayTime\\":(\d+).*?'
    r'\\"brief\\":\\"(.*?)\\"\}',
    re.S,
)


class AnnounceError(Exception):
    """Raised when the announcement feed cannot be read."""


def _unescape(value: str) -> str:
    """Unescape the payload strings that the page embeds in a JS literal.

    Args:
        value: Raw escaped fragment.

    Returns:
        Readable text.
    """
    text = str(value or "")
    for source, target in (
        ("\\\\", "\\"),
        ('\\"', '"'),
        ("\\n", "\n"),
        ("\\/", "/"),
        ("\\u003c", "<"),
        ("\\u003e", ">"),
        ("\\u0026", "&"),
    ):
        text = text.replace(source, target)
    return html_module.unescape(text).strip()


def html_to_text(markup: str) -> str:
    """Flatten announcement HTML into readable plain text.

    Args:
        markup: Raw HTML fragment.

    Returns:
        Whitespace-normalized text.
    """
    text = _BLOCK_RE.sub(" ", str(markup or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_images(markup: str, base_url: str = "") -> list[str]:
    """Collect image URLs from an announcement body.

    Args:
        markup: Announcement body HTML.
        base_url: Page URL, used to resolve relative sources.

    Returns:
        Absolute, de-duplicated URLs in document order.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for raw in _IMG_RE.findall(str(markup or "")):
        candidate = raw.strip()
        if not candidate:
            continue
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        elif not candidate.startswith("http"):
            candidate = urljoin(base_url, candidate)
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def classify(text: str) -> tuple[str, str]:
    """Classify an announcement from its copy.

    Args:
        text: Title plus brief.

    Returns:
        Tuple of a stable key and its Chinese label.
    """
    blob = str(text or "")
    if any(marker in blob for marker in _SYSTEM_MARKERS):
        return "SYSTEM", "系统"
    if any(marker in blob for marker in _ACTIVITY_MARKERS):
        return "ACTIVITY", "活动"
    return "NOTICE", "公告"


def _format_time(stamp: Any) -> str:
    """Format a publish timestamp.

    Args:
        stamp: Unix timestamp.

    Returns:
        ``YYYY-MM-DD HH:MM``, or an empty string when unusable.
    """
    try:
        seconds = int(stamp or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def parse_list(page: str) -> list[dict[str, Any]]:
    """Parse the announcement list out of the news page.

    Args:
        page: Raw HTML of the news page.

    Returns:
        Normalized announcements, newest first.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in GROUP_KEYS:
        marker = re.search(r'\\"' + group + r'\\":\{\\"list\\":\[', page)
        if not marker:
            continue
        for blob in _ITEM_RE.finditer(page[marker.end() :]):
            cid, stamp, brief = blob.group(1), blob.group(2), blob.group(3)
            if cid in seen:
                continue
            seen.add(cid)
            chunk = blob.group(0)
            title = re.search(r'\\"title\\":\\"(.*?)\\"', chunk, re.S)
            author = re.search(r'\\"author\\":\\"(.*?)\\"', chunk, re.S)
            title_text = _unescape(title.group(1)) if title else cid
            brief_text = _unescape(brief)
            group_key, group_label = classify(f"{title_text} {brief_text}")
            records.append(
                {
                    "id": cid,
                    "title": title_text,
                    "author": _unescape(author.group(1)) if author else "",
                    "brief": brief_text,
                    "group": group_key,
                    "group_cn": group_label,
                    "url": DETAIL_URL.format(cid=cid),
                    "ts": int(stamp),
                    "date_text": _format_time(stamp),
                }
            )
    records.sort(key=lambda item: (item["ts"], int(item["id"] or 0)), reverse=True)
    return records


def extract_body(page: str) -> str:
    """Extract one announcement's rendered body from its detail page.

    The body is the innermost ``div`` wrapping the first paragraph or image after
    the date header. Starting from the content element and walking back to its
    container avoids depending on the hashed class names, which change on every
    build.

    Args:
        page: Raw HTML of an announcement detail page.

    Returns:
        The body HTML, or an empty string when it cannot be located.
    """
    marker = DATE_MARKER_RE.search(page)
    if not marker:
        return ""
    candidates = [
        position
        for position in (page.find("<p", marker.end()), page.find("<img", marker.end()))
        if position >= 0
    ]
    if not candidates:
        return ""
    container = page.rfind("<div", marker.end(), min(candidates))
    if container < 0:
        return ""
    depth, index = 0, container
    while index < len(page):
        opening = page.find("<div", index)
        closing = page.find("</div>", index)
        if closing < 0:
            break
        if 0 <= opening < closing:
            depth += 1
            index = opening + 4
        else:
            depth -= 1
            index = closing + 6
            if depth == 0:
                return page[container:index]
    return ""


class AnnounceClient:
    """Reads the official announcement feed."""

    def __init__(
        self,
        news_url: str = NEWS_URL,
        detail_url: str = DETAIL_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            news_url: Announcement list page.
            detail_url: Detail URL template containing ``{cid}``.
            client: Optional pre-built HTTP client, used by tests.
        """
        self.news_url = news_url
        self.detail_url = detail_url
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
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot-Arknights)"},
            )
            self._owns_client = True
        return self._client

    async def _get_text(self, url: str) -> str:
        """Fetch a page as text.

        Args:
            url: Absolute URL.

        Returns:
            Response body.

        Raises:
            AnnounceError: When the request fails.
        """
        try:
            response = await self._get_client().get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            raise AnnounceError(f"公告获取失败: {exc}") from exc

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch the announcement list.

        Returns:
            Announcements newest first.

        Raises:
            AnnounceError: When the list page cannot be read or parsed.
        """
        records = parse_list(await self._get_text(self.news_url))
        if not records:
            raise AnnounceError("公告列表解析失败，页面结构可能已变化")
        return records

    async def fetch_detail(self, cid: str) -> dict[str, Any]:
        """Fetch one announcement together with its rendered body.

        Args:
            cid: Announcement id.

        Returns:
            Mapping with ``body_html``, ``text``, ``images`` and ``image_total``.

        Raises:
            AnnounceError: When the announcement cannot be read.
        """
        cid = str(cid or "").strip()
        if not cid:
            raise AnnounceError("公告编号为空")
        url = self.detail_url.format(cid=cid)
        page = await self._get_text(url)
        body = extract_body(page)
        images = extract_images(body, url)
        return {
            "cid": cid,
            "url": url,
            "body_html": body,
            "text": html_to_text(body),
            "images": images,
            "image_total": len(images),
        }
