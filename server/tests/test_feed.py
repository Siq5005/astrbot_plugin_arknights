"""Feed normalisation is pure, so it is tested without touching the network."""

import time

import pytest
from app.feed import FeedError, document_to_text, fetch_official, normalize


def test_document_to_text_joins_text_blocks_in_order():
    document = {
        "blockIds": ["a", "b", "c"],
        "blockMap": {
            "b": {
                "kind": "text",
                "text": {
                    "inlineElements": [{"kind": "text", "text": {"text": "第二行"}}]
                },
            },
            "a": {
                "kind": "text",
                "text": {
                    "inlineElements": [{"kind": "text", "text": {"text": "第一行"}}]
                },
            },
            "c": {"kind": "image", "image": {"id": "x"}},
        },
    }

    assert document_to_text(document) == "第一行\n第二行"


def test_document_to_text_tolerates_missing_fields():
    assert document_to_text({}) == ""
    assert document_to_text({"blockIds": ["a"], "blockMap": {}}) == ""


def test_normalize_maps_list_item_to_stable_shape():
    item = {
        "id": "6377378",
        "title": "《明日方舟》「书行山海」特别公益PV",
        "viewKind": 1,
        "publishedAtTs": "1791709243",
        "thumbnail": "https://bbs.hycdn.cn/cover.webp",
        "imageList": [
            {
                "url": "https://bbs.hycdn.cn/a.webp",
                "infos": [{"url": "https://bbs.hycdn.cn/a-inner.webp"}],
            }
        ],
        "tagIds": [474],
    }
    tags = [{"id": 474, "name": "明日方舟"}, {"id": 505, "name": "泰拉记事社"}]

    record = normalize(item, tags=tags)

    assert record["id"] == "6377378"
    assert record["kind"] == 1
    assert record["published_at"] == 1791709243
    assert record["cover"] == "https://bbs.hycdn.cn/cover.webp"
    assert record["images"] == ["https://bbs.hycdn.cn/a.webp"]
    assert record["tags"] == ["明日方舟", "泰拉记事社"]
    assert record["url"] == "https://www.skland.com/article?id=6377378"
    assert record["text"] == ""


def test_normalize_uses_thumbnail_when_image_list_is_empty():
    item = {
        "id": "1",
        "title": "t",
        "viewKind": 3,
        "publishedAtTs": 10,
        "thumbnail": "https://x/y.webp",
    }

    record = normalize(item)

    assert record["cover"] == "https://x/y.webp"
    assert record["images"] == []


def test_normalize_falls_back_to_first_image_for_cover():
    item = {
        "id": "1",
        "title": "t",
        "viewKind": 3,
        "publishedAtTs": 10,
        "imageList": [{"url": "https://bbs.hycdn.cn/a.webp"}],
    }

    record = normalize(item)

    assert record["cover"] == "https://bbs.hycdn.cn/a.webp"


def test_normalize_reads_text_from_document():
    item = {"id": "1", "title": "t", "viewKind": 1, "publishedAtTs": 10}
    detail = {
        "document": {
            "blockIds": ["a"],
            "blockMap": {
                "a": {
                    "kind": "text",
                    "text": {
                        "inlineElements": [{"kind": "text", "text": {"text": "正文"}}]
                    },
                }
            },
        }
    }

    assert normalize(item, detail_item=detail)["text"] == "正文"


class _FakeSkland:
    """Minimal stand-in for SklandClient, recording requested URLs."""

    def __init__(self, pages):
        self._pages = pages
        self.urls = []

    async def get_device_id(self):
        return "did"

    async def get_authorization(self, user_token):
        return "auth"

    async def get_credential(self, authorization):
        return type("Cred", (), {"cred": "c", "token": "t"})()

    def _signed_headers(self, url, method, body, cred, did):
        return {}

    async def _request(self, method, url, headers=None, json_data=None, content=None):
        self.urls.append(url)
        return self._pages.pop(0)


@pytest.mark.anyio
async def test_fetch_official_never_exceeds_page_size_ten():
    fake = _FakeSkland(
        [
            {"code": 0, "data": {"list": [], "hasMore": False, "pageToken": ""}},
        ]
    )

    await fetch_official(fake, "tok")

    assert "pageSize=10" in fake.urls[0]


@pytest.mark.anyio
async def test_fetch_official_raises_on_business_error():
    fake = _FakeSkland([{"code": 10001, "message": "参数错误"}])

    with pytest.raises(FeedError, match="参数错误"):
        await fetch_official(fake, "tok")


@pytest.mark.anyio
async def test_fetch_official_follows_page_token_dedupes_and_orders_newest_first():
    now = int(time.time())
    oldest_id = "page-one-oldest"
    duplicate_id = "repeated-across-pages"
    newest_id = "page-two-newest"
    fake = _FakeSkland(
        [
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "item": {
                                "id": oldest_id,
                                "title": "first page, older",
                                "viewKind": 1,
                                "publishedAtTs": now - 600,
                            }
                        },
                        {
                            "item": {
                                "id": duplicate_id,
                                "title": "first page, repeated later",
                                "viewKind": 1,
                                "publishedAtTs": now - 120,
                            }
                        },
                    ],
                    "hasMore": True,
                    "pageToken": "page-2-token",
                },
            },
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "item": {
                                "id": newest_id,
                                "title": "second page, newest",
                                "viewKind": 1,
                                "publishedAtTs": now - 60,
                            }
                        },
                        {
                            "item": {
                                "id": duplicate_id,
                                "title": "second page, repeated",
                                "viewKind": 1,
                                "publishedAtTs": now - 120,
                            }
                        },
                    ],
                    "hasMore": False,
                    "pageToken": "",
                },
            },
        ]
    )

    records = await fetch_official(fake, "tok", now=now)

    # One upstream request per page served.
    assert len(fake.urls) == 2
    # The second request carries the token the first page returned.
    assert "pageToken" not in fake.urls[0]
    assert "pageToken=page-2-token" in fake.urls[1]
    # Newest first, regardless of the order the pages arrived in.
    assert [record["id"] for record in records] == [
        newest_id,
        duplicate_id,
        oldest_id,
    ]
    assert [record["published_at"] for record in records] == sorted(
        (record["published_at"] for record in records), reverse=True
    )
    # An id repeated across pages is emitted once.
    assert [record["id"] for record in records].count(duplicate_id) == 1
