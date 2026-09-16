import httpx
import pytest

from core.skland import Credential, SklandClient, SklandError

CRED = Credential(token="tok", cred="cred")


def _client(handler):
    client = SklandClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._did = "Btest"
    return client


@pytest.mark.anyio
async def test_get_binding_list_parses_arknights_only():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "appCode": "arknights",
                            "bindingList": [
                                {
                                    "uid": "1",
                                    "nickName": "探姬#9315",
                                    "channelName": "官服",
                                    "channelMasterId": "1",
                                }
                            ],
                        },
                        {"appCode": "endfield", "bindingList": [{"uid": "9"}]},
                    ]
                },
            },
        )

    bindings = await _client(handler).get_binding_list(CRED)
    assert [b.uid for b in bindings] == ["1"]
    assert bindings[0].nickname == "探姬#9315"
    assert bindings[0].channel_name == "官服"
    assert bindings[0].game_id == "1"


@pytest.mark.anyio
async def test_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 10001, "message": "用户未登录"})

    with pytest.raises(SklandError, match="用户未登录"):
        await _client(handler).get_binding_list(CRED)


@pytest.mark.anyio
async def test_http_401_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"message": "unauthorized"})

    with pytest.raises(SklandError):
        await _client(handler).get_player_info(CRED, "1")


@pytest.mark.anyio
async def test_malformed_json_raises():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(SklandError):
        await _client(handler).get_player_info(CRED, "1")


@pytest.mark.anyio
async def test_transport_error_raises():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(SklandError):
        await _client(handler).get_player_info(CRED, "1")


@pytest.mark.anyio
async def test_sign_arknights_reports_awards():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "awards": [
                        {
                            "resource": {"id": "4003", "name": "合成玉"},
                            "count": 500,
                        }
                    ]
                },
            },
        )

    from core.skland import UserBinding

    result = await _client(handler).sign_arknights(CRED, UserBinding(uid="1"))
    assert result.success is True
    assert result.awards == ["合成玉x500"]


@pytest.mark.anyio
async def test_sign_arknights_already_signed_is_not_an_exception():
    def handler(request):
        return httpx.Response(200, json={"code": 10001, "message": "今日已签到"})

    from core.skland import UserBinding

    result = await _client(handler).sign_arknights(CRED, UserBinding(uid="1"))
    assert result.success is False
    assert result.error == "今日已签到"


@pytest.mark.anyio
async def test_signature_headers_are_sent():
    seen = {}

    def handler(request):
        seen["did"] = request.headers.get("dId")
        seen["cred"] = request.headers.get("cred")
        seen["sign"] = request.headers.get("sign")
        return httpx.Response(200, json={"code": 0, "data": {}})

    await _client(handler).get_player_info(CRED, "1")
    assert seen["did"] == "Btest"
    assert seen["cred"] == "cred"
    assert seen["sign"] and len(seen["sign"]) == 32


def test_parse_sanity_reads_status_ap():
    data = {"status": {"ap": {"current": 10, "max": 135, "completeRecoveryTime": -1}}}
    assert SklandClient.parse_sanity(data, now=1_000_000.0) == {
        "current": 135,
        "max": 135,
        "complete_recovery_time": -1,
    }


def test_parse_sanity_extrapolates():
    data = {
        "status": {"ap": {"current": 1, "max": 135, "completeRecoveryTime": 1_003_600}}
    }
    parsed = SklandClient.parse_sanity(data, now=1_000_000.0)
    assert parsed["current"] == 125
    assert parsed["max"] == 135


@pytest.mark.anyio
async def test_sign_arknights_sends_a_json_content_type():
    """Attendance is the only raw-body POST, and Skland 400s without the header."""
    seen = {}

    def handler(request):
        seen["content-type"] = request.headers.get("content-type")
        seen["body"] = request.content
        return httpx.Response(200, json={"code": 0, "data": {"awards": []}})

    from core.skland import UserBinding

    await _client(handler).sign_arknights(CRED, UserBinding(uid="1"))
    assert seen["content-type"] == "application/json"
    # the signed bytes must be the transmitted bytes
    assert seen["body"] == b'{"gameId":"1","uid":"1"}'


@pytest.mark.anyio
async def test_http_error_surfaces_sklands_own_message():
    """A bare status code is useless; Skland explains the reason in the body."""

    def handler(request):
        return httpx.Response(400, json={"code": 10002, "message": "登录状态已失效"})

    from core.skland import UserBinding

    with pytest.raises(SklandError) as excinfo:
        await _client(handler).sign_arknights(CRED, UserBinding(uid="1"))
    assert "登录状态已失效" in str(excinfo.value)


@pytest.mark.anyio
async def test_http_error_without_a_body_still_reports_the_status():
    def handler(request):
        return httpx.Response(400, text="<html>gateway</html>")

    from core.skland import UserBinding

    with pytest.raises(SklandError) as excinfo:
        await _client(handler).sign_arknights(CRED, UserBinding(uid="1"))
    assert "400" in str(excinfo.value)
