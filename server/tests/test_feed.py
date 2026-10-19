"""Feed normalisation is pure, so it is tested without touching the network."""

import time

import pytest
from app.details import DetailStore
from app.feed import (
    PAGE_SIZE,
    FeedError,
    document_to_text,
    fetch_official,
    normalize,
)


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

    def __init__(self, pages, details=None):
        self._pages = list(pages)
        self._details = dict(details or {})
        self.urls = []
        self.detail_urls = []

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
        if "/web/v2/item" in url:
            self.detail_urls.append(url)
            item_id = url.split("id=", 1)[1].split("&", 1)[0]
            result = self._details.get(item_id)
            if isinstance(result, Exception):
                raise result
            if result is not None:
                return result
            return {"code": 0, "data": {"item": {}}}
        return self._pages.pop(0)


@pytest.mark.anyio
async def test_fetch_official_requests_five_items():
    fake = _FakeSkland(
        [
            {"code": 0, "data": {"list": [], "hasMore": False, "pageToken": ""}},
        ]
    )

    await fetch_official(fake, "tok")

    assert "pageSize=5" in fake.urls[0]


@pytest.mark.anyio
async def test_fetch_official_keeps_only_the_first_page_size_rows():
    now = int(time.time())
    # The upstream may ignore ``pageSize`` and return more rows; only the first
    # PAGE_SIZE of them may become records.
    rows = [_list_row(str(index), f"t{index}", now - 60 * index) for index in range(8)]
    fake = _FakeSkland([_list_page(rows)])

    records = await fetch_official(fake, "tok", now=now)

    assert [record["id"] for record in records] == ["0", "1", "2", "3", "4"]


@pytest.mark.anyio
async def test_fetch_official_raises_on_business_error():
    fake = _FakeSkland([{"code": 10001, "message": "参数错误"}])

    with pytest.raises(FeedError, match="参数错误"):
        await fetch_official(fake, "tok")


@pytest.mark.anyio
async def test_fetch_official_makes_exactly_one_request():
    now = int(time.time())
    fake = _FakeSkland(
        [
            {
                "code": 0,
                "data": {
                    "list": [
                        # Deliberately not newest-first, with gamma repeated, so
                        # the sort and the same-page dedupe are both exercised.
                        _list_row("gamma", "gamma older", now - 180),
                        _list_row("alpha", "alpha", now - 60),
                        _list_row("beta", "beta", now - 120),
                        _list_row("gamma", "gamma repeated", now - 300),
                    ],
                    "hasMore": True,
                    "pageToken": "next-page-token",
                },
            },
            # Trap for a paging regression: this second page must never be
            # requested. If paging is reintroduced, the fetcher follows
            # hasMore/pageToken and this test fails on the URL count below.
            {
                "code": 0,
                "data": {
                    "list": [_list_row("d", "delta", now - 240)],
                    "hasMore": False,
                    "pageToken": "",
                },
            },
        ]
    )

    records = await fetch_official(fake, "tok", now=now)

    assert len(fake.urls) == 1
    assert "pageToken" not in fake.urls[0]
    assert [record["id"] for record in records] == ["alpha", "beta", "gamma"]


def _detail_envelope(text):
    """Build a detail-endpoint payload whose item carries ``text`` as its body."""
    return {
        "code": 0,
        "data": {
            "item": {
                "document": {
                    "blockIds": ["a"],
                    "blockMap": {
                        "a": {
                            "kind": "text",
                            "text": {
                                "inlineElements": [
                                    {"kind": "text", "text": {"text": text}}
                                ]
                            },
                        }
                    },
                }
            }
        },
    }


def _list_row(item_id, title, published_at):
    return {
        "item": {
            "id": item_id,
            "title": title,
            "viewKind": 1,
            "publishedAtTs": published_at,
        },
        "tags": [],
    }


def _list_page(rows):
    return {"code": 0, "data": {"list": rows, "hasMore": False, "pageToken": ""}}


@pytest.mark.anyio
async def test_fetch_official_fetches_detail_once_and_reuses_the_cache(tmp_path):
    store = DetailStore(tmp_path / "state.json")
    now = int(time.time())
    page = _list_page([_list_row("1", "t", now - 60)])

    first = _FakeSkland([page], details={"1": _detail_envelope("正文")})
    records = await fetch_official(first, "tok", now=now, details=store)
    assert records[0]["text"] == "正文"
    assert len(first.detail_urls) == 1

    # A second refresh re-reads the same window; the cached body must not be
    # fetched again.
    second = _FakeSkland([page], details={"1": _detail_envelope("正文")})
    records = await fetch_official(second, "tok", now=now, details=store)
    assert records[0]["text"] == "正文"
    assert len(second.detail_urls) == 0


@pytest.mark.anyio
async def test_fetch_official_survives_a_failing_detail(tmp_path):
    store = DetailStore(tmp_path / "state.json")
    now = int(time.time())
    page = _list_page(
        [
            _list_row("good", "good", now - 60),
            _list_row("bad", "bad", now - 30),
        ]
    )
    fake = _FakeSkland(
        [page],
        details={
            "good": _detail_envelope("好正文"),
            "bad": {"code": 10001, "message": "参数错误"},
        },
    )

    records = await fetch_official(fake, "tok", now=now, details=store)

    by_id = {record["id"]: record for record in records}
    assert len(records) == 2
    assert by_id["good"]["text"] == "好正文"
    assert by_id["bad"]["text"] == ""


@pytest.mark.anyio
async def test_fetch_official_enriches_every_item_on_the_single_page(tmp_path):
    store = DetailStore(tmp_path / "state.json")
    now = int(time.time())
    rows = [_list_row(str(i), f"t{i}", now - i) for i in range(PAGE_SIZE)]
    fake = _FakeSkland(
        [_list_page(rows)],
        details={str(i): _detail_envelope(f"正文{i}") for i in range(len(rows))},
    )

    records = await fetch_official(fake, "tok", now=now, details=store)

    assert len(fake.detail_urls) == PAGE_SIZE
    assert len([r for r in records if r["text"]]) == PAGE_SIZE
