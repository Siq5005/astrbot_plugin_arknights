import httpx
import pytest

from core.announce import (
    GROUP_CN,
    AnnounceClient,
    AnnounceError,
    html_to_text,
    normalize,
)

META = {
    "focusAnnounceId": "2068",
    "announceList": [
        {
            "announceId": "2069",
            "title": "05月08日\n闪断更新公告",
            "isWebUrl": True,
            "webUrl": "https://ak.hycdn.cn/announce/Android/announcement/2069_1746619406.html",
            "day": 8,
            "month": 5,
            "group": "SYSTEM",
        },
        {
            "announceId": "2068",
            "title": "【布道自由】\n限定寻访开启",
            "isWebUrl": True,
            "webUrl": "https://ak.hycdn.cn/announce/Android/announcement/2068_1746074007.html",
            "day": 1,
            "month": 5,
            "group": "ACTIVITY",
        },
    ],
}


def _client(handler):
    return AnnounceClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_html_to_text_flattens_markup():
    markup = "<html><head><style>p{color:red}</style></head><body><p>第一行</p><p>第二行<br/>续行</p>"
    text = html_to_text(markup)
    assert "color:red" not in text
    assert "第一行" in text
    assert "第二行" in text
    assert "续行" in text
    assert "<" not in text


def test_html_to_text_unescapes_entities():
    assert "&" in html_to_text("<p>A &amp; B</p>")
    assert "「" in html_to_text("<p>&#12300;测试&#12301;</p>")


def test_html_to_text_handles_empty():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


def test_normalize_reads_timestamp_from_url():
    record = normalize(META["announceList"][0])
    assert record["id"] == "2069"
    # the two line title is collapsed for display
    assert record["title"] == "05月08日 闪断更新公告"
    assert record["group_cn"] == "系统"
    assert record["ts"] == 1746619406
    assert record["date_text"].startswith("2025-05-07") or record[
        "date_text"
    ].startswith("2025-05-08")


def test_normalize_falls_back_to_month_day():
    record = normalize(
        {"announceId": "1", "title": "t", "month": 7, "day": 3, "group": "MYSTERY"}
    )
    assert record["ts"] == 0
    assert record["date_text"] == "07-03"
    assert record["group_cn"] == "公告"


def test_group_map_covers_the_observed_groups():
    assert GROUP_CN["SYSTEM"] == "系统"
    assert GROUP_CN["ACTIVITY"] == "活动"


@pytest.mark.anyio
async def test_fetch_sorts_newest_first():
    def handler(request):
        return httpx.Response(200, json=META)

    records = await _client(handler).fetch()
    assert [record["id"] for record in records] == ["2069", "2068"]


@pytest.mark.anyio
async def test_fetch_skips_malformed_entries():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "announceList": [
                    {"title": "no id"},
                    "not-a-dict",
                    META["announceList"][0],
                ]
            },
        )

    records = await _client(handler).fetch()
    assert [record["id"] for record in records] == ["2069"]


@pytest.mark.anyio
async def test_fetch_raises_on_transport_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(AnnounceError, match="公告获取失败"):
        await _client(handler).fetch()


@pytest.mark.anyio
async def test_fetch_raises_on_malformed_json():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(AnnounceError):
        await _client(handler).fetch()


@pytest.mark.anyio
async def test_focus_id():
    def handler(request):
        return httpx.Response(200, json=META)

    assert await _client(handler).focus_id() == "2068"


@pytest.mark.anyio
async def test_focus_id_survives_failure():
    def handler(request):
        raise httpx.ConnectError("boom")

    assert await _client(handler).focus_id() == ""


@pytest.mark.anyio
async def test_detail_flattens_and_truncates():
    def handler(request):
        return httpx.Response(200, text="<p>" + "字" * 2000 + "</p>")

    text = await _client(handler).detail("https://example.invalid/a.html", limit=50)
    assert len(text) == 50


@pytest.mark.anyio
async def test_detail_requires_a_url():
    with pytest.raises(AnnounceError):
        await AnnounceClient().detail("")
