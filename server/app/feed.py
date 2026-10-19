"""Read the Arknights "official" column from Skland and normalise it.

Skland exposes the community content API on the same host the plugin already
signs against. The official column is ``gameId=1`` (Arknights) plus
``cateId=1`` (the platform's own "官方" category, whose ``kind`` is 100/Admin),
sorted newest first with ``sortType=2``.

Only the first page is read, capped at ``pageSize=5``. The upstream throttles
under sustained load, so paging the list would multiply requests without
adding any of the newest five items the feed actually serves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

ZONAI_BASE = "https://zonai.skland.com"
OFFICIAL_GAME_ID = 1
OFFICIAL_CATE_ID = 1
PAGE_SIZE = 5
FEED_PATH = "/web/v2/home/index?gameId={game}&cateId={cate}&pageSize={size}&sortType=2"
ARTICLE_URL_TEMPLATE = "https://www.skland.com/article?id={id}"

# Detail requests are one per item, spaced out to avoid a burst of requests per
# refresh; the cache makes that progress durable across refreshes.
_DETAIL_DELAY_SECONDS = 0.5


class FeedError(Exception):
    """Raised when the official feed cannot be read."""


def document_to_text(document: dict[str, Any]) -> str:
    """Flatten a Skland rich-text document into plain text.

    Blocks are ordered by ``blockIds``; only text blocks contribute.

    Args:
        document: The ``document`` object of a Skland content item.

    Returns:
        Newline-joined block text, empty when there is none.
    """
    if not isinstance(document, dict):
        return ""
    block_map = document.get("blockMap")
    block_ids = document.get("blockIds")
    if not isinstance(block_map, dict) or not isinstance(block_ids, list):
        return ""

    lines: list[str] = []
    for block_id in block_ids:
        block = block_map.get(block_id)
        if not isinstance(block, dict) or block.get("kind") != "text":
            continue
        text_prop = block.get("text")
        if not isinstance(text_prop, dict):
            continue
        elements = text_prop.get("inlineElements")
        if not isinstance(elements, list):
            continue
        parts: list[str] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            inner = element.get("text")
            if isinstance(inner, dict) and inner.get("text"):
                parts.append(str(inner["text"]))
        line = "".join(parts)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _image_urls(item: dict[str, Any]) -> list[str]:
    """Collect the image URLs of an item.

    Args:
        item: Raw Skland content item.

    Returns:
        Deduplicated image URLs in feed order.
    """
    urls: list[str] = []
    for entry in item.get("imageList") or []:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        if url and url not in urls:
            urls.append(url)
    return urls


def normalize(
    item: dict[str, Any],
    detail_item: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reduce a raw Skland item to the aggregator's stable wire shape.

    Args:
        item: Raw item, either from the feed list or the detail endpoint.
        detail_item: Detail payload when available; supplies the body text.
        tags: Tag objects from the feed row.

    Returns:
        A dict with ``id``, ``title``, ``kind``, ``published_at``, ``cover``,
        ``images``, ``text``, ``url`` and ``tags``.
    """
    source = detail_item or item
    item_id = str(source.get("id") or item.get("id") or "")
    images = _image_urls(source) or _image_urls(item)
    cover = str(source.get("thumbnail") or item.get("thumbnail") or "")
    if not cover and images:
        cover = images[0]
    if not cover:
        # The video cover lives on videoList when the item has no thumbnail.
        for video in source.get("videoList") or []:
            if isinstance(video, dict):
                inner = video.get("cover")
                if isinstance(inner, dict) and inner.get("url"):
                    cover = str(inner["url"])
                    break

    text = document_to_text(source.get("document") or {})
    if not text:
        texts = source.get("texts")
        if isinstance(texts, list):
            text = "\n".join(
                str(entry.get("content") or "")
                for entry in texts
                if isinstance(entry, dict) and entry.get("content")
            )

    tag_names = [
        str(tag.get("name"))
        for tag in (tags or [])
        if isinstance(tag, dict) and tag.get("name")
    ]

    try:
        published_at = int(
            source.get("publishedAtTs") or item.get("publishedAtTs") or 0
        )
    except (TypeError, ValueError):
        published_at = 0

    try:
        kind = int(source.get("viewKind") or item.get("viewKind") or 0)
    except (TypeError, ValueError):
        kind = 0

    return {
        "id": item_id,
        "title": str(source.get("title") or item.get("title") or ""),
        "kind": kind,
        "published_at": published_at,
        "cover": cover,
        "images": images,
        "text": text,
        "url": ARTICLE_URL_TEMPLATE.format(id=item_id),
        "tags": tag_names,
    }


async def fetch_official(
    client: Any,
    user_token: str,
    window_hours: int = 72,
    now: int | None = None,
    details: Any | None = None,
) -> list[dict[str, Any]]:
    """Read the Arknights official column, newest first.

    Only the first page is fetched, so at most ``PAGE_SIZE`` items are kept:
    the upstream throttles under sustained load, and paging is both wasteful
    and unnecessary for the newest few posts this feed serves.

    Args:
        client: A signed ``SklandClient`` instance.
        user_token: Long-lived Hypergryph passport token.
        window_hours: Skip items older than this many hours.
        now: Unix seconds to compare against; defaults to the system clock.
        details: Optional ``DetailStore``; when provided, empty item bodies are
            filled from the cache or fetched once and remembered.

    Returns:
        Normalised records, newest first.

    Raises:
        FeedError: When the feed cannot be read.
    """
    did = await client.get_device_id()
    authorization = await client.get_authorization(user_token)
    cred = await client.get_credential(authorization)

    reference = int(now if now is not None else time.time())
    cutoff = reference - max(1, window_hours) * 3600

    records: list[dict[str, Any]] = []
    raw_by_id: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    seen: set[str] = set()

    path = FEED_PATH.format(
        game=OFFICIAL_GAME_ID, cate=OFFICIAL_CATE_ID, size=PAGE_SIZE
    )
    url = ZONAI_BASE + path
    headers = client._signed_headers(url, "GET", None, cred, did)
    try:
        payload = await client._request("GET", url, headers=headers)
    except Exception as exc:  # noqa: BLE001 - surfaced as FeedError
        raise FeedError(f"森空岛接口请求失败: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or "")
        raise FeedError(f"森空岛接口返回异常: {message or payload}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise FeedError("森空岛接口响应缺少 data")
    # The upstream may ignore ``pageSize``; keep the operator's hard cap local.
    rows = (data.get("list") or [])[:PAGE_SIZE]

    for row in rows:
        raw = row.get("item") if isinstance(row, dict) else None
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        row_tags = row.get("tags") or []
        record = normalize(raw, tags=row_tags)
        if record["published_at"] and record["published_at"] < cutoff:
            continue
        records.append(record)
        raw_by_id[item_id] = (raw, row_tags)

    records.sort(key=lambda entry: (entry["published_at"], entry["id"]), reverse=True)

    if details is not None:
        fetched = 0
        for record in records:
            if record["text"]:
                continue
            cached = details.get(record["id"])
            if cached is not None:
                record["text"] = cached
                continue
            if fetched:
                await asyncio.sleep(_DETAIL_DELAY_SECONDS)
            fetched += 1
            raw, row_tags = raw_by_id[record["id"]]
            try:
                detail_url = f"{ZONAI_BASE}/web/v2/item?id={record['id']}"
                detail_headers = client._signed_headers(
                    detail_url, "GET", None, cred, did
                )
                payload = await client._request(
                    "GET", detail_url, headers=detail_headers
                )
                if not isinstance(payload, dict) or payload.get("code") not in (
                    0,
                    None,
                ):
                    raise FeedError(f"森空岛详情接口返回异常: {payload}")
                data = payload.get("data")
                item = data.get("item") if isinstance(data, dict) else None
                if not isinstance(item, dict):
                    raise FeedError("森空岛详情响应缺少 item")
                record["text"] = normalize(raw, detail_item=item, tags=row_tags)["text"]
                details.put(record["id"], record["text"])
            except Exception as exc:  # noqa: BLE001 - one bad post must not sink the feed
                logger.warning("skipping detail for item %s: %s", record["id"], exc)
        details.prune({record["id"] for record in records})
        details.save()

    return records
