import json

import httpx
import pytest

from core.gamedata import GameData

META = {
    "gachaPoolClient": [
        {
            "gachaPoolId": "NORM_0_1_1",
            "gachaPoolName": "适合多种场合的强力干员",
            "gachaRuleType": 0,
            "openTime": 1548727200,
            "endTime": 1557950399,
        },
        {"gachaPoolId": "LIMITED_1", "gachaPoolName": "限定寻访", "gachaRuleType": 2},
    ]
}

UP = {
    "gachaPoolClient": [
        {
            "gachaPoolId": "NORM_0_1_1",
            "gachaPoolDetail": {
                "detailInfo": {
                    "upCharInfo": {
                        "perCharList": [
                            {"rarityRank": 5, "charIdList": ["char_103_angel"]},
                            {"rarityRank": 4, "charIdList": ["char_171_bldsk"]},
                        ]
                    }
                }
            },
        },
        {
            # no upCharInfo at all -> fall back to availCharInfo
            "gachaPoolId": "AVAIL_ONLY",
            "gachaPoolDetail": {
                "detailInfo": {
                    "availCharInfo": {
                        "perCharList": [
                            {"rarityRank": 5, "charIdList": ["char_999_x"]},
                        ]
                    }
                }
            },
        },
    ]
}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_meta():
    meta = GameData._parse_meta(META)
    assert meta["NORM_0_1_1"]["name"] == "适合多种场合的强力干员"
    assert meta["NORM_0_1_1"]["rule_type"] == 0
    assert meta["NORM_0_1_1"]["open_time"] == 1548727200
    assert meta["LIMITED_1"]["rule_type"] == 2
    # missing times default to zero rather than raising
    assert meta["LIMITED_1"]["open_time"] == 0


def test_parse_up_prefers_up_char_info():
    up = GameData._parse_up(UP)
    assert up["NORM_0_1_1"]["six"] == ["char_103_angel"]
    assert up["NORM_0_1_1"]["five"] == ["char_171_bldsk"]
    # pools without upCharInfo still resolve from availCharInfo
    assert up["AVAIL_ONLY"]["six"] == ["char_999_x"]


def test_parse_up_accepts_a_bare_list():
    assert GameData._parse_up(UP["gachaPoolClient"])["NORM_0_1_1"]["six"] == [
        "char_103_angel"
    ]


def test_parse_up_tolerates_garbage():
    assert GameData._parse_up(None) == {}
    assert GameData._parse_up({"gachaPoolClient": ["not-a-dict"]}) == {}


@pytest.mark.anyio
async def test_ensure_downloads_and_caches(tmp_path):
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        if "prts" in str(request.url):
            return httpx.Response(200, json=UP)
        return httpx.Response(200, json=META)

    data = GameData(tmp_path, client=_client(handler))
    assert await data.ensure() is True
    assert len(calls) == 2
    assert data.pool_name("NORM_0_1_1") == "适合多种场合的强力干员"
    assert data.up_six("NORM_0_1_1") == ["char_103_angel"]
    assert data.pool_name("missing") == "missing"
    assert data.up_six("missing") == []

    # Second call is served from the cache, so no further downloads happen.
    before = len(calls)
    assert await data.ensure() is True
    assert len(calls) == before
    assert (tmp_path / "gacha_meta.json").is_file()
    assert (tmp_path / "gacha_up.json").is_file()


@pytest.mark.anyio
async def test_ensure_uses_the_second_mirror(tmp_path):
    seen: list[str] = []

    def handler(request):
        url = str(request.url)
        seen.append(url)
        if "prts" in url:
            return httpx.Response(200, json=UP)
        if "jsdelivr" in url:
            return httpx.Response(500)
        return httpx.Response(200, json=META)

    data = GameData(tmp_path, client=_client(handler))
    assert await data.ensure() is True
    assert any("jsdelivr" in url for url in seen)
    assert any("raw.githubusercontent" in url for url in seen)
    assert data.pool_name("LIMITED_1") == "限定寻访"


@pytest.mark.anyio
async def test_ensure_reports_failure_without_meta(tmp_path):
    def handler(request):
        return httpx.Response(500)

    data = GameData(tmp_path, client=_client(handler))
    assert await data.ensure() is False
    assert data.pool_meta == {}


@pytest.mark.anyio
async def test_meta_survives_up_failure(tmp_path):
    def handler(request):
        if "prts" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=META)

    data = GameData(tmp_path, client=_client(handler))
    assert await data.ensure() is True
    assert data.pool_name("LIMITED_1") == "限定寻访"
    assert data.pool_up == {}


@pytest.mark.anyio
async def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "gacha_meta.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "gacha_up.json").write_text("{not json", encoding="utf-8")
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        if "prts" in str(request.url):
            return httpx.Response(200, json=UP)
        return httpx.Response(200, json=META)

    data = GameData(tmp_path, client=_client(handler))
    assert await data.ensure() is True
    assert len(calls) == 2
    assert json.loads((tmp_path / "gacha_meta.json").read_text())["gachaPoolClient"]
