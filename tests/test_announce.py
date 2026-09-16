"""Tests for the website-backed announcement reader."""

import httpx
import pytest

from core.announce import (
    AnnounceClient,
    AnnounceError,
    classify,
    extract_body,
    extract_images,
    html_to_text,
    parse_list,
)


def escaped(payload: str) -> str:
    """The site embeds its payload in a JS string, so quotes arrive escaped."""
    return payload.replace('"', '\\"')


NEWS_PAGE = (
    "<html><script>window.x = '"
    + escaped(
        '{"ANNOUNCEMENT":{"list":['
        '{"cid":"7367","tab":"0","sticky":false,'
        '"title":"[明日方舟]09月11日16:00闪断更新公告",'
        '"author":"【明日方舟】运营组","displayTime":1789095600,'
        '"cover":"","extraCover":"","brief":"计划将于09月11日进行服务器闪断更新。"},'
        '{"cid":"9681","tab":"0","sticky":false,'
        '"title":"[活动预告]「月行水上」限时活动即将开启",'
        '"author":"【明日方舟】运营组","displayTime":1787900000,'
        '"cover":"","extraCover":"","brief":"活动期间将开放活动关卡。"}'
        "]}}"
    )
    + "'</script></html>"
)

DETAIL_PAGE = (
    '<div class="_a">公告</div>'
    '<div class="_b">[明日方舟]09月11日16:00闪断更新公告</div>'
    '<div class="_c">2026 // 09 / 11</div>'
    '<div class="_d"></div>'
    '<div class="_e"><div class="_f"><div class="_g">'
    '<img src="https://cdn.example/banner.jpg">'
    "<p>感谢您对《明日方舟》的关注与支持。</p>"
    "<p><strong>闪断补偿：</strong>合成玉*200</p>"
    "</div></div></div>"
    '<div class="footer">页脚</div>'
)


def _client(handler):
    return AnnounceClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_html_to_text_flattens_markup():
    text = html_to_text("<p>第一段</p><p>第二段<br/>续行</p>")
    assert "第一段" in text
    assert "第二段" in text
    assert "续行" in text
    assert "<" not in text


def test_html_to_text_handles_empty():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


def test_classify_prefers_system_then_activity():
    assert classify("09月11日16:00闪断更新公告")[1] == "系统"
    assert classify("「月行水上」限时活动即将开启")[1] == "活动"
    assert classify("[明日方舟]运营组说明")[1] == "系统"
    assert classify("普通通知")[1] == "公告"


def test_parse_list_reads_the_embedded_payload():
    records = parse_list(NEWS_PAGE)
    assert [r["id"] for r in records] == ["7367", "9681"]
    first = records[0]
    assert first["title"] == "[明日方舟]09月11日16:00闪断更新公告"
    assert first["author"] == "【明日方舟】运营组"
    assert first["group"] == "SYSTEM"
    assert first["group_cn"] == "系统"
    assert first["ts"] == 1789095600
    assert first["date_text"].startswith("2026-")
    assert records[1]["group_cn"] == "活动"
    # newest first
    assert records[0]["ts"] > records[1]["ts"]


def test_parse_list_ignores_the_latest_aggregate():
    page = "<x>" + escaped(
        '{"LATEST":{"list":[{"cid":"1","displayTime":100,'
        '"title":"t","author":"a","brief":"b"}]}}'
    )
    assert parse_list(page) == []


def test_parse_list_handles_a_missing_payload():
    assert parse_list("<html>nothing here</html>") == []


def test_extract_body_keeps_paragraphs_and_images():
    body = extract_body(DETAIL_PAGE)
    assert "感谢您对《明日方舟》的关注与支持。" in body
    assert "闪断补偿" in body
    assert "https://cdn.example/banner.jpg" in body
    # the surrounding chrome is excluded
    assert "页脚" not in body
    assert "2026 // 09 / 11" not in body


def test_extract_body_returns_empty_without_the_date_marker():
    assert extract_body("<div><p>no date header</p></div>") == ""


def test_extract_body_keeps_a_leading_image():
    """The body often opens with a banner before any paragraph."""
    page = (
        '<div class="_x">2026 // 09 / 11</div><div class="_y"></div>'
        '<div class="_z"><img src="https://cdn.example/lead.jpg"><p>正文</p></div>'
    )
    body = extract_body(page)
    assert "lead.jpg" in body
    assert "正文" in body


def test_extract_images_makes_urls_absolute_and_unique():
    markup = (
        '<img src="https://cdn.example/a.jpg"/>'
        '<img src="https://cdn.example/a.jpg"/>'
        '<img src="//cdn.example/b.png"/>'
        '<img src="images/c.png"/>'
    )
    urls = extract_images(markup, "https://ak.hypergryph.com/news/1")
    assert urls == [
        "https://cdn.example/a.jpg",
        "https://cdn.example/b.png",
        "https://ak.hypergryph.com/news/images/c.png",
    ]


def test_extract_images_handles_empty():
    assert extract_images("") == []
    assert extract_images(None) == []


@pytest.mark.anyio
async def test_fetch_reads_the_news_page():
    def handler(request):
        assert request.url.path == "/news"
        return httpx.Response(200, text=NEWS_PAGE)

    records = await _client(handler).fetch()
    assert len(records) == 2


@pytest.mark.anyio
async def test_fetch_raises_when_the_page_shape_changes():
    def handler(request):
        return httpx.Response(200, text="<html>redesigned</html>")

    with pytest.raises(AnnounceError, match="解析失败"):
        await _client(handler).fetch()


@pytest.mark.anyio
async def test_fetch_raises_on_transport_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(AnnounceError, match="公告获取失败"):
        await _client(handler).fetch()


@pytest.mark.anyio
async def test_fetch_detail_returns_body_and_images():
    def handler(request):
        assert request.url.path == "/news/7367"
        return httpx.Response(200, text=DETAIL_PAGE)

    detail = await _client(handler).fetch_detail("7367")
    assert "https://cdn.example/banner.jpg" in detail["body_html"]
    assert detail["images"] == ["https://cdn.example/banner.jpg"]
    assert detail["image_total"] == 1
    assert "闪断补偿" in detail["text"]


@pytest.mark.anyio
async def test_fetch_detail_requires_an_id():
    with pytest.raises(AnnounceError):
        await AnnounceClient().fetch_detail("")


@pytest.mark.anyio
async def test_fetch_detail_handles_an_empty_body():
    def handler(request):
        return httpx.Response(200, text="<html><body>no body</body></html>")

    detail = await _client(handler).fetch_detail("1")
    assert detail["body_html"] == ""
    assert detail["images"] == []
