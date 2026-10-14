"""The self-hosted feed client normalises into the website record shape."""

import httpx
import pytest

from core.feed import FeedClient, FeedError


def _client(handler, base_url="https://ark.youyou.ink/api/ark/v1", api_key="k"):
    transport = httpx.MockTransport(handler)
    return FeedClient(
        base_url=base_url,
        api_key=api_key,
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.anyio
async def test_fetch_normalises_into_announce_shape():
    def handler(request):
        assert request.headers["X-API-Key"] == "k"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": False,
                    "items": [
                        {
                            "id": "6377378",
                            "title": "《明日方舟》「书行山海」特别公益PV",
                            "kind": 1,
                            "published_at": 1791709243,
                            "cover": "https://bbs.hycdn.cn/cover.webp",
                            "images": ["https://bbs.hycdn.cn/cover.webp"],
                            "text": "书页翻过山海，故事走向四方。",
                            "url": "https://www.skland.com/article?id=6377378",
                            "tags": ["明日方舟"],
                        }
                    ],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == "6377378"
    assert record["ts"] == 1791709243
    assert record["kind"] == 1
    assert record["group_cn"] == "官方"
    assert record["cover"] == "https://bbs.hycdn.cn/cover.webp"
    assert record["images"] == ["https://bbs.hycdn.cn/cover.webp"]
    assert record["image_total"] == 1
    assert record["text"] == "书页翻过山海，故事走向四方。"
    assert "书页翻过山海" in record["body_html"]
    assert record["stale"] is False
    # The website record carries a display date; the feed must supply one too.
    assert record["date_text"]


@pytest.mark.anyio
async def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(FeedError):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_raises_feed_error_on_malformed_base_url():
    """A mistyped base URL degrades as FeedError, never as raw httpx.InvalidURL.

    An invalid port makes ``httpx.URL`` raise ``httpx.InvalidURL`` while the
    request is built. ``InvalidURL`` does not subclass ``httpx.HTTPError``, so
    without the widened except clause it would escape as a non-``FeedError`` and
    bypass the degradation path, which keys on ``FeedError`` only.
    """

    def handler(request):
        raise AssertionError("the request must never reach the transport")

    client = _client(handler, base_url="https://ark.youyou.ink:notaport/api/ark/v1")
    with pytest.raises(FeedError, match="Invalid port") as excinfo:
        await client.fetch()
    await client.close()

    # The cause proves InvalidURL really fired and was translated, rather than
    # the test passing because some other failure produced a FeedError.
    assert isinstance(excinfo.value.__cause__, httpx.InvalidURL)


@pytest.mark.anyio
async def test_fetch_raises_on_401():
    def handler(request):
        return httpx.Response(
            401, json={"code": 401, "message": "缺少或无效的 X-API-Key"}
        )

    client = _client(handler)
    with pytest.raises(FeedError, match="X-API-Key"):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_raises_on_business_error_code():
    def handler(request):
        return httpx.Response(200, json={"code": 500, "message": "服务内部错误"})

    client = _client(handler)
    with pytest.raises(FeedError, match="服务内部错误"):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_raises_on_malformed_payload():
    """A 200 envelope without ``items`` is malformed and must raise FeedError."""

    def handler(request):
        return httpx.Response(200, json={"code": 0, "data": {"stale": False}})

    client = _client(handler)
    with pytest.raises(FeedError):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_survives_unexpected_item_shapes():
    """Odd field types are coerced, so no raw exception bypasses degradation."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": True,
                    "items": [
                        "not-a-dict",
                        {"id": "", "title": "no id"},
                        {
                            "id": 42,
                            "title": None,
                            "kind": "video",
                            "published_at": "yesterday",
                            "cover": None,
                            "images": "https://bbs.hycdn.cn/cover.webp",
                            "text": None,
                            "url": None,
                        },
                    ],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == "42"
    assert record["title"] == "42"
    assert record["ts"] == 0
    assert record["kind"] == 0
    assert record["images"] == []
    assert record["image_total"] == 0
    assert record["stale"] is True


@pytest.mark.anyio
async def test_fetch_survives_out_of_range_timestamp():
    """An out-of-range timestamp renders as unknown instead of escaping.

    ``datetime.fromtimestamp(10**19)`` raises ``OverflowError``, which is an
    ``ArithmeticError`` and therefore not a ``ValueError``/``OSError``/
    ``TypeError``. Without the widened except clause it escapes ``fetch()`` as a
    non-``FeedError`` and bypasses the degradation path, which keys on
    ``FeedError`` only.
    """

    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": False,
                    "items": [
                        {
                            "id": "7",
                            "title": "t",
                            "kind": 1,
                            "published_at": 10**19,
                            "text": "b",
                            "url": "https://x/7",
                        }
                    ],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == "7"
    assert record["ts"] == 10**19
    assert record["date_text"] == ""


@pytest.mark.anyio
async def test_body_html_escapes_text_and_orders_images():
    """The card body is HTML-safe and lists the cover before the other images."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": False,
                    "items": [
                        {
                            "id": "1",
                            "title": "<b>t</b>",
                            "kind": 3,
                            "published_at": 1791709243,
                            "cover": "https://x/cover.webp",
                            "images": ["https://x/other.webp", "https://x/cover.webp"],
                            "text": "<script>alert('x')</script>",
                            "url": "https://x/1",
                        }
                    ],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    record = records[0]
    assert "&lt;script&gt;" in record["body_html"]
    assert "<script>" not in record["body_html"]
    assert record["images"] == ["https://x/cover.webp", "https://x/other.webp"]
    assert record["image_total"] == 2
    assert record["body_html"].index("cover.webp") < record["body_html"].index(
        "other.webp"
    )


@pytest.mark.anyio
async def test_trailing_slash_and_borrowed_client_ownership():
    """A trailing slash is trimmed and ``close`` leaves a borrowed client open."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"code": 0, "data": {"stale": False, "items": []}}
        )

    borrowed = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = FeedClient(
        base_url="https://ark.youyou.ink/api/ark/v1/",
        api_key="k",
        client=borrowed,
    )
    assert await client.fetch() == []
    assert seen["url"] == "https://ark.youyou.ink/api/ark/v1/feed"
    await client.close()
    assert borrowed.is_closed is False
    await borrowed.aclose()


@pytest.mark.anyio
async def test_fetch_translates_decoding_error_from_json():
    """A ``DecodingError`` inside ``response.json()`` degrades as ``FeedError``.

    ``httpx.DecodingError`` subclasses ``httpx.HTTPError``, not ``ValueError``.
    In httpx 0.28 the content-decoding failure surfaces during the eager
    ``response.read()`` inside ``get()``, where the transport clause already
    translates it. This test pins the ``.json()`` clause itself with a
    hand-built response, so a future httpx (or a streaming client) that raises
    ``DecodingError`` from ``.json()`` cannot bypass degradation.
    """

    class DecodingResponse:
        status_code = 200

        def json(self):
            raise httpx.DecodingError("truncated gzip body")

    class DecodingClient:
        async def get(self, url, headers=None):
            return DecodingResponse()

    client = FeedClient(client=DecodingClient())
    with pytest.raises(FeedError, match="响应格式异常") as excinfo:
        await client.fetch()
    await client.close()

    # The cause proves DecodingError really fired and was translated, rather
    # than the test passing because some other failure produced a FeedError.
    assert isinstance(excinfo.value.__cause__, httpx.DecodingError)


@pytest.mark.anyio
async def test_fetch_raises_when_stale_and_empty():
    """A stale envelope with no items fails loudly instead of stopping the push."""

    def handler(request):
        return httpx.Response(
            200, json={"code": 0, "data": {"stale": True, "items": []}}
        )

    client = _client(handler)
    with pytest.raises(FeedError, match="无数据"):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_returns_records_when_stale_but_nonempty():
    """Serving older cached data under ``stale=true`` keeps working as before."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": True,
                    "items": [{"id": "1", "title": "t", "published_at": 100}],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    assert len(records) == 1
    assert records[0]["stale"] is True


@pytest.mark.anyio
async def test_health_returns_the_data_object():
    def handler(request):
        assert request.url.path.endswith("/health")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": True,
                    "count": 3,
                    "last_success_at": 1,
                    "last_error": "boom",
                },
            },
        )

    client = _client(handler)
    try:
        data = await client.health()
    finally:
        await client.close()

    assert data["stale"] is True
    assert data["last_error"] == "boom"


@pytest.mark.anyio
async def test_health_raises_feed_error_on_transport_failure():
    def handler(request):
        raise httpx.ConnectError("down")

    client = _client(handler)
    with pytest.raises(FeedError):
        await client.health()
    await client.close()


@pytest.mark.anyio
async def test_health_raises_feed_error_on_missing_data():
    def handler(request):
        return httpx.Response(200, json={"code": 0})

    client = _client(handler)
    with pytest.raises(FeedError, match="data"):
        await client.health()
    await client.close()
