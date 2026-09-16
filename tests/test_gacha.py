from types import SimpleNamespace

import httpx
import pytest

from core.gacha import (
    FALLBACK_CATEGORIES,
    GachaClient,
    GachaError,
    analyze,
    format_record_time,
)


def _client(handler):
    return GachaClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_format_record_time():
    assert format_record_time(0) == ""
    assert format_record_time(None) == ""
    assert format_record_time("junk") == ""
    assert len(format_record_time(1700000000)) == 11


@pytest.mark.anyio
async def test_grant_token():
    def handler(request):
        assert request.url.path == "/user/oauth2/v2/grant"
        return httpx.Response(200, json={"status": 0, "data": {"token": "grant1"}})

    assert await _client(handler).grant_token("pass") == "grant1"


@pytest.mark.anyio
async def test_grant_token_rejects_expired_passport():
    def handler(request):
        return httpx.Response(200, json={"status": 1, "msg": "token无效"})

    with pytest.raises(GachaError, match="重新执行"):
        await _client(handler).grant_token("bad")


@pytest.mark.anyio
async def test_role_token():
    def handler(request):
        assert "u8_token_by_uid" in request.url.path
        return httpx.Response(200, json={"code": 0, "data": {"token": "role1"}})

    assert await _client(handler).role_token("grant1", "uid1") == "role1"


@pytest.mark.anyio
async def test_role_token_missing_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 1, "message": "角色不存在"})

    with pytest.raises(GachaError, match="角色不存在"):
        await _client(handler).role_token("grant1", "uid1")


@pytest.mark.anyio
async def test_center_cookie_reads_set_cookie():
    def handler(request):
        return httpx.Response(
            200,
            json={"code": 0},
            headers={"set-cookie": "ak-user-center=COOKIE1; Path=/"},
        )

    assert await _client(handler).center_cookie("role1") == "COOKIE1"


@pytest.mark.anyio
async def test_center_cookie_missing_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 0})

    with pytest.raises(GachaError, match="登录抽卡页面失败"):
        await _client(handler).center_cookie("role1")


@pytest.mark.anyio
async def test_categories_from_endpoint():
    def handler(request):
        return httpx.Response(
            200,
            json={"code": 0, "data": [{"id": "normal"}, {"cateId": "classic"}]},
        )

    result = await _client(handler).categories("uid", "pass", "role", "cookie")
    assert result == ["normal", "classic"]


@pytest.mark.anyio
async def test_categories_falls_back():
    def handler(request):
        return httpx.Response(500)

    result = await _client(handler).categories("uid", "pass", "role", "cookie")
    assert result == list(FALLBACK_CATEGORIES)


@pytest.mark.anyio
async def test_history_page_reads_list_and_reports_more():
    def handler(request):
        records = [{"gachaTs": 100 - i, "pos": i, "rarity": 3} for i in range(100)]
        return httpx.Response(200, json={"code": 0, "data": {"list": records}})

    page, more = await _client(handler).history_page("uid", "normal", "p", "r", "c")
    assert len(page) == 100
    assert more is True


@pytest.mark.anyio
async def test_history_page_reads_gacha_list_key():
    def handler(request):
        return httpx.Response(
            200, json={"code": 0, "data": {"gachaList": [{"gachaTs": 1, "pos": 0}]}}
        )

    page, more = await _client(handler).history_page("uid", "normal", "p", "r", "c")
    assert len(page) == 1
    assert more is False


@pytest.mark.anyio
async def test_history_page_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 400, "message": "分类不存在"})

    with pytest.raises(GachaError, match="分类不存在"):
        await _client(handler).history_page("uid", "normal", "p", "r", "c")


@pytest.mark.anyio
async def test_fetch_records_walks_the_whole_chain_and_dedupes():
    """Every category is fetched, pages are followed, duplicates collapse."""
    seen: list[str] = []

    def handler(request):
        path = request.url.path
        seen.append(path)
        if path.endswith("/grant"):
            return httpx.Response(200, json={"status": 0, "data": {"token": "grant"}})
        if path.endswith("u8_token_by_uid"):
            return httpx.Response(200, json={"code": 0, "data": {"token": "role"}})
        if path.endswith("/role/login"):
            return httpx.Response(
                200,
                json={"code": 0},
                headers={"set-cookie": "ak-user-center=CK; Path=/"},
            )
        if path.endswith("/gacha/cate"):
            return httpx.Response(200, json={"code": 0, "data": [{"id": "normal"}]})
        if path.endswith("/gacha/history"):
            params = dict(request.url.params)
            if "gachaTs" not in params:
                # a full page so the client keeps paging, with a duplicate
                records = [
                    {"gachaTs": 200 - i, "pos": i, "rarity": 3, "charName": f"c{i}"}
                    for i in range(100)
                ]
            else:
                records = [{"gachaTs": 50, "pos": 0, "rarity": 5, "charName": "六星"}]
            return httpx.Response(200, json={"code": 0, "data": {"list": records}})
        raise AssertionError(f"unexpected path {path}")

    records = await _client(handler).fetch_records("pass", "uid1")
    # 100 from page one plus one from page two, all unique
    assert len(records) == 101
    # newest first
    assert int(records[0]["gachaTs"]) == 200
    assert int(records[-1]["gachaTs"]) == 50
    # the full chain ran exactly once
    assert sum(1 for path in seen if path.endswith("/grant")) == 1
    assert sum(1 for path in seen if path.endswith("u8_token_by_uid")) == 1


def _record(ts, rarity, char_id="", pool="P1", pos=0, is_new=False, pool_name=None):
    return {
        "gachaTs": ts,
        "pos": pos,
        "rarity": rarity,
        "charId": char_id,
        "poolId": pool,
        "poolName": pool_name or f"卡池 {pool}",
        "isNew": is_new,
    }


def test_analyze_counts_sequence_and_pity():
    records = [
        _record(10, 2),
        _record(20, 3),
        _record(30, 5, "char_A"),
        _record(40, 2),
        _record(50, 3),
        _record(60, 4),
        _record(70, 2),
        _record(80, 3),
        _record(90, 2),
        _record(100, 5, "char_B"),
    ]
    ctx = analyze(records)
    assert ctx["total"] == 10
    assert ctx["counts"][6] == 2
    assert ctx["counts"][5] == 1
    assert ctx["counts"][4] == 3
    assert ctx["counts"][3] == 4
    assert ctx["six_total"] == 2
    assert ctx["avg_six"] == 5.0
    # newest six star is the last pull, so nothing has been pulled since
    assert ctx["pity"] == 0
    assert [item["pulls"] for item in ctx["six_stars"]] == [7, 3]


def test_analyze_detects_up_and_off_rate():
    gamedata = SimpleNamespace(
        pool_name=lambda pool_id: "限定寻访",
        up_six=lambda pool_id: ["char_A"],
    )
    records = [
        _record(10, 2),
        _record(20, 5, "char_A"),
        _record(30, 2),
        _record(40, 2),
        _record(50, 5, "char_B"),
        _record(60, 2),
    ]
    ctx = analyze(records, gamedata=gamedata)
    assert ctx["up_known"] is True
    assert ctx["up_hits"] == 1
    assert ctx["off_rate"] == 1
    six = {item["char_id"]: item for item in ctx["six_stars"]}
    assert six["char_A"]["is_up"] is True
    assert six["char_B"]["is_up"] is False
    assert six["char_A"]["pool_name"] == "限定寻访"


def test_analyze_leaves_up_unknown_without_pool_data():
    records = [_record(10, 5, "char_A"), _record(20, 2)]
    ctx = analyze(records)
    assert ctx["up_known"] is False
    assert ctx["six_stars"][0]["is_up"] is None


def test_analyze_reports_current_pity():
    records = [_record(10, 5, "char_A")] + [_record(20 + i, 2) for i in range(7)]
    ctx = analyze(records)
    # eight pulls in total; the six star was the first, so seven since
    assert ctx["pity"] == 7
    assert ctx["six_stars"][0]["pulls"] == 1


def test_analyze_resolves_names_from_char_info():
    char_info = {"char_X": {"name": "阿米娅"}}
    ctx = analyze([_record(10, 5, "char_X")], char_info=char_info)
    assert ctx["six_stars"][0]["name"] == "阿米娅"


def test_analyze_groups_pools():
    records = [
        _record(10, 5, "char_A", pool="P1"),
        _record(20, 2, pool="P1"),
        _record(30, 4, pool="P2"),
        _record(40, 2, pool="P2"),
        _record(50, 2, pool="P2"),
    ]
    ctx = analyze(records)
    by_name = {pool["name"]: pool for pool in ctx["pools"]}
    assert by_name["卡池 P2"]["count"] == 3
    assert by_name["卡池 P1"]["six"] == 1
    assert ctx["pools"][0]["count"] == 3


def test_analyze_handles_no_records():
    ctx = analyze([])
    assert ctx["total"] == 0
    assert ctx["six_total"] == 0
    assert ctx["avg_six"] == 0.0
    assert ctx["pity"] == 0
    assert ctx["six_stars"] == []


def test_analyze_handles_missing_fields():
    # a missing rarity falls back to the gacha floor rather than inventing a
    # one-star bucket
    ctx = analyze([{"rarity": None}, {}])
    assert ctx["total"] == 2
    assert ctx["counts"][3] == 2
    assert ctx["counts"][6] == 0


@pytest.mark.anyio
async def test_records_from_different_categories_are_not_deduped():
    """The cursor pair is only unique within a category.

    Two categories can both report (gachaTs=100, pos=0). Keying the dedupe on
    the cursor alone silently dropped one of them, which under-counted every
    statistic downstream — the failure mode reported for special banners.
    """

    def handler(request):
        path = request.url.path
        if path.endswith("/grant"):
            return httpx.Response(200, json={"status": 0, "data": {"token": "g"}})
        if path.endswith("u8_token_by_uid"):
            return httpx.Response(200, json={"code": 0, "data": {"token": "r"}})
        if path.endswith("/role/login"):
            return httpx.Response(
                200,
                json={"code": 0},
                headers={"set-cookie": "ak-user-center=CK; Path=/"},
            )
        if path.endswith("/gacha/cate"):
            return httpx.Response(
                200, json={"code": 0, "data": [{"id": "normal"}, {"id": "special"}]}
            )
        if path.endswith("/gacha/history"):
            category = dict(request.url.params).get("category")
            # identical cursor pair, different character per category
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "gachaTs": 100,
                                "pos": 0,
                                "rarity": 5,
                                "charId": f"char_{category}",
                                "poolId": "NORM_0_1_1",
                            }
                        ]
                    },
                },
            )
        raise AssertionError(f"unexpected path {path}")

    records = await _client(handler).fetch_records("pass", "uid1")
    assert len(records) == 2
    assert {record["category"] for record in records} == {"normal", "special"}


def _pool_record(ts, rarity, pool_id, char_id="", pos=0):
    return {
        "gachaTs": ts,
        "pos": pos,
        "rarity": rarity,
        "charId": char_id,
        "poolId": pool_id,
        "poolName": "",
    }


def test_analyze_splits_banners_and_tracks_pity_per_family():
    """Pity must be per banner family, not one running total across banners."""
    records = [
        # standard banner: six star on the 2nd pull, then 3 more pulls
        _pool_record(10, 2, "NORM_0_1_1"),
        _pool_record(20, 5, "NORM_0_1_1", "char_A"),
        _pool_record(30, 2, "NORM_0_1_1"),
        _pool_record(40, 2, "NORM_0_1_1"),
        _pool_record(50, 2, "NORM_0_1_1"),
        # limited banner: six star on the 1st pull of *that* banner
        _pool_record(60, 5, "LIMITED_9_0_3", "char_B"),
        _pool_record(70, 2, "LIMITED_9_0_3"),
    ]
    ctx = analyze(records)
    assert ctx["total"] == 7
    assert ctx["six_total"] == 2
    # globally the newest six star is followed by one pull
    assert ctx["pity"] == 1

    by_label = {banner["label"]: banner for banner in ctx["banners"]}
    assert set(by_label) == {"标准寻访", "限定寻访"}
    assert by_label["标准寻访"]["total"] == 5
    # within the standard family the latest six star is the 2nd pull, and three
    # pulls follow it
    assert by_label["标准寻访"]["pity"] == 3
    assert by_label["标准寻访"]["six_total"] == 1
    assert by_label["限定寻访"]["total"] == 2
    assert by_label["限定寻访"]["pity"] == 1
    assert ctx["banner_count"] == 2
    # newest family first
    assert ctx["banners"][0]["label"] == "限定寻访"


def test_analyze_does_not_count_off_rate_without_up_data():
    """A pool with no rate-up table must not be scored as an off-rate."""

    class NoUp:
        @staticmethod
        def pool_name(pool_id):
            return pool_id

        @staticmethod
        def up_six(pool_id):
            return []

    records = [
        _pool_record(10, 5, "SPECIAL_54_0_5", "char_A"),
        _pool_record(20, 5, "SPECIAL_54_0_5", "char_B"),
    ]
    ctx = analyze(records, gamedata=NoUp())
    assert ctx["up_known"] is False
    assert ctx["up_hits"] == 0
    assert ctx["off_rate"] == 0
    assert all(item["is_up"] is None for item in ctx["six_stars"])


def test_analyze_scores_up_for_joint_banner_with_multiple_six_stars():
    """Joint banners list several six stars; all of them count as UP."""

    class Joint:
        @staticmethod
        def pool_name(pool_id):
            return "联合作战寻访"

        @staticmethod
        def up_six(pool_id):
            return ["char_A", "char_B", "char_C"]

    records = [
        _pool_record(10, 5, "SPECIAL_54_0_5", "char_A"),
        _pool_record(20, 5, "SPECIAL_54_0_5", "char_C"),
    ]
    ctx = analyze(records, gamedata=Joint())
    assert ctx["up_known"] is True
    assert ctx["up_hits"] == 2
    assert ctx["off_rate"] == 0
    assert ctx["banners"][0]["label"] == "定向甄选"
    assert ctx["luck"] in {"欧皇", "偏欧", "平稳", "偏非", "非酋"}
