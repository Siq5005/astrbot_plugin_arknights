import httpx
import pytest

from core.hypergryph import HypergryphClient, HypergryphError


def _client(handler):
    client = HypergryphClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.anyio
async def test_create_qr_returns_scan_id_and_url():
    def handler(request):
        assert request.url.path == "/general/v1/gen_scan/login"
        return httpx.Response(
            200,
            json={
                "status": 0,
                "data": {
                    "scanId": "abc",
                    "scanUrl": "hypergryph://scan_login?scanId=abc",
                },
            },
        )

    qr = await _client(handler).create_qr()
    assert qr["scan_id"] == "abc"
    assert qr["scan_url"].startswith("hypergryph://")


@pytest.mark.anyio
async def test_create_qr_uses_skland_app_code():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(
            200, json={"status": 0, "data": {"scanId": "a", "scanUrl": "u"}}
        )

    await _client(handler).create_qr()
    assert "4ca99fa6b56cc2ba" in seen["body"]


@pytest.mark.anyio
async def test_poll_qr_pending_returns_none():
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"status": 100, "msg": "未扫码"})

    assert await _client(handler).poll_qr("abc") is None


@pytest.mark.anyio
async def test_poll_qr_scanned_returns_code():
    def handler(request):
        return httpx.Response(200, json={"status": 0, "data": {"scanCode": "sc1"}})

    assert await _client(handler).poll_qr("abc") == "sc1"


@pytest.mark.anyio
async def test_poll_qr_scanned_but_unconfirmed_keeps_polling():
    """The real bug: a scanned code reports its own status and must not abort.

    Production returned ``{"status": 101, "msg": "已扫码待确认"}`` the moment the
    user scanned, and the old code raised on it, so the login died before the
    user could tap confirm. Only status 0 finishes the poll.
    """

    def handler(request):
        return httpx.Response(200, json={"status": 101, "msg": "已扫码待确认"})

    assert await _client(handler).poll_qr("abc") is None


@pytest.mark.anyio
async def test_poll_qr_any_intermediate_status_keeps_polling():
    for status in (1, 101, 102, 200):

        def handler(request, status=status):
            return httpx.Response(200, json={"status": status, "msg": "处理中"})

        assert await _client(handler).poll_qr("abc") is None


@pytest.mark.anyio
async def test_get_token_by_scan_code_returns_token():
    def handler(request):
        assert request.url.path == "/user/auth/v1/token_by_scan_code"
        return httpx.Response(200, json={"status": 0, "data": {"token": "T1"}})

    assert await _client(handler).get_token_by_scan_code("sc1") == "T1"


@pytest.mark.anyio
async def test_get_token_by_scan_code_rejects_on_business_error():
    def handler(request):
        return httpx.Response(200, json={"status": 1, "msg": "扫码凭证无效"})

    with pytest.raises(HypergryphError, match="扫码凭证无效"):
        await _client(handler).get_token_by_scan_code("bad")


@pytest.mark.anyio
async def test_transport_error_raises_hypergryph_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(HypergryphError):
        await _client(handler).create_qr()
