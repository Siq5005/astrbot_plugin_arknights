"""Unit tests for the garrison (卫戍协议) record mapping and context builder."""

import pytest

from core.garrison import (
    GarrisonClient,
    build_context,
    build_maps,
    build_user,
    difficulty_label,
    format_ts,
    mode_label,
    pick_char,
    prepare_record,
    roman_level,
)
from core.skland import Credential

RESOURCE = {
    "seasons": [
        {"seasonId": "act3autochess", "name": "规程", "phase": 0, "phaseName": ""}
    ],
    "versionInfo": {
        "seasonId": "act3autochess",
        "versionId": "V3_1",
        "phase": 1,
        "phaseName": "序列I",
    },
    "strategies": [
        {
            "strategyId": "band_weakness",
            "iconUrl": "https://example.invalid/band_weakness.png",
            "initiatorName": "陈",
            "name": "以己之长",
        }
    ],
    "bonds": [
        {
            "bondId": "yanShip",
            "iconUrl": "https://example.invalid/yanShip.png",
            "name": "炎",
            "activeCount": 3,
        },
        {
            "bondId": "soloShip",
            "iconUrl": "https://example.invalid/soloShip.png",
            "name": "独行",
            "activeCount": 0,
        },
    ],
    "chars": [
        {
            "charId": "char_1039_thorn2",
            "avatarUrl": "https://example.invalid/char_1039_thorn2.png",
            "halfBodyUrl": "https://example.invalid/half_1039_thorn2.png",
            "name": "引星棘刺",
            "skills": [],
            "modules": [],
        }
    ],
    "items": [
        {
            "itemId": "chess_item_2_10_e_a",
            "iconUrl": "https://example.invalid/chess_item_2_10_e_a.png",
            "name": "灵巧涡轮手套",
        }
    ],
}

RECORD = {
    "id": "6379755-act3autochess-1794154580",
    "completeState": 0,
    "trophyBefore": 15,
    "trophyAfter": 16,
    "coinCost": 74,
    "syncCnt": 4,
    "killCnt": 104,
    "bandId": "band_weakness",
    "title": "",
    "bondInfo": [
        {"bondId": "soloShip", "layer": 0, "activate": 0},
        {"bondId": "yanShip", "layer": 4, "activate": 1},
    ],
    "chessSquad": [
        {
            "chessId": "chess_char_6_01_a",
            "equips": [{"equipId": "chess_item_2_10_e_a"}],
            "chessInfo": {
                "id": "chess_char_6_01_a",
                "charId": "char_1039_thorn2",
                "charName": "引星棘刺",
                "chessLevel": 6,
                "upgradeNum": 3,
            },
            "moduleId": "uniequip_002_thorn2",
            "skillId": "skchr_thorn2_2",
            "charId": "char_1039_thorn2",
        }
    ],
    "passRound": 7,
    "gameStartTs": "1794154580",
    "gameEndTs": "1794156731",
    "modeType": "MULTI",
    "modeDifficulty": "HARD",
    "versionId": "V3_1",
    "activityId": "act3autochess",
}

PLAYER_INFO = {
    "status": {
        "uid": "6379755",
        "name": "Coe#7127",
        "level": 120,
        "avatar": {"url": "https://example.invalid/avatar.png"},
        "secretary": {"charId": "char_002_amiya", "skinId": "char_1001_amiya2#1"},
    }
}


def test_roman_level():
    assert roman_level(1) == "I"
    assert roman_level(4) == "IV"
    assert roman_level(6) == "VI"
    assert roman_level(0) == "0"
    assert roman_level(None) == "0"
    assert roman_level("3") == "III"
    # Out-of-range levels clamp instead of crashing.
    assert roman_level(9) == "VIII"


def test_mode_labels():
    assert mode_label("MULTI") == "联合模拟"
    assert mode_label("SINGLE") == "独立模拟"
    assert mode_label("LOCAL") == "本地模拟"
    assert mode_label("") == "-"
    assert mode_label("UNKNOWN") == "UNKNOWN"


def test_difficulty_labels():
    assert difficulty_label("FUNNY") == "标准模拟"
    assert difficulty_label("NORMAL") == "险境模拟"
    assert difficulty_label("HARD") == "绝境模拟"
    assert difficulty_label("ABYSS") == "终极模拟"
    assert difficulty_label("") == "-"


def test_build_maps_indexes_by_id():
    maps = build_maps(RESOURCE)
    assert maps["bands"]["band_weakness"]["name"] == "以己之长"
    assert maps["bonds"]["yanShip"]["name"] == "炎"
    assert maps["chars"]["char_1039_thorn2"]["name"] == "引星棘刺"
    assert maps["items"]["chess_item_2_10_e_a"]["name"] == "灵巧涡轮手套"


def test_prepare_record_maps_fields():
    record = prepare_record(RECORD, build_maps(RESOURCE))
    assert record["success"] is False
    assert record["title"] == "模拟失败"
    assert record["pass_round"] == 7
    assert record["mode"] == "联合模拟"
    assert record["difficulty"] == "绝境模拟"
    assert record["strategy_name"] == "以己之长"
    assert record["band_icon"].endswith("band_weakness.png")
    assert record["trophy_before"] == 15
    assert record["trophy_after"] == 16
    assert record["kill_cnt"] == 104
    assert record["coin_cost"] == 74
    # syncCnt is intentionally not surfaced on the card.
    assert "sync_cnt" not in record
    # Chess cells carry only the portrait, Roman level and equip icons.
    unit = record["squad"][0]
    assert unit["roman"] == "VI"
    assert unit["avatar"].endswith("char_1039_thorn2.png")
    assert [e["icon"] for e in unit["equips"]] == [
        "https://example.invalid/chess_item_2_10_e_a.png"
    ]
    # Activated bonds sort first, then by descending layer.
    assert [b["name"] for b in record["bonds"]] == ["炎", "独行"]
    assert record["bonds"][0]["layer"] == 4
    assert record["bonds"][0]["activate"] is True


def test_prepare_record_ignores_record_title():
    # The badge always spells out the outcome, even when the payload carries a
    # ``title``; the raw field is empty in practice and must not win.
    success = prepare_record(
        {**RECORD, "title": "自定义", "completeState": 1}, build_maps(RESOURCE)
    )
    assert success["success"] is True
    assert success["title"] == "模拟成功"

    failure = prepare_record(
        {**RECORD, "title": "自定义", "completeState": 0}, build_maps(RESOURCE)
    )
    assert failure["success"] is False
    assert failure["title"] == "模拟失败"


def test_pick_char_tolerates_non_numeric_level():
    # A malformed ``chessLevel`` degrades to level 0 instead of raising outside
    # the command's try/except.
    unit = pick_char(
        build_maps(RESOURCE),
        {"chessInfo": {"charId": "char_1039_thorn2", "chessLevel": "unknown"}},
    )
    assert unit["level"] == 0
    assert unit["roman"] == "0"


def test_format_ts_invalid_yields_dash():
    assert format_ts(None) == "-"
    assert format_ts("not-a-number") == "-"


def test_build_user_falls_back_to_char_names():
    user = build_user(PLAYER_INFO, build_maps(RESOURCE), {"char_002_amiya": "阿米娅"})
    assert user["uid"] == "6379755"
    assert user["name"] == "Coe#7127"
    assert user["level"] == 120
    assert user["avatar"].endswith("avatar.png")
    # Amiya is absent from the guide resource, so the plugin's own table wins.
    assert user["secretary_name"] == "阿米娅"
    assert user["secretary_icon"] == ""


def test_build_user_without_secretary_is_empty():
    user = build_user({"status": {"uid": "1"}}, build_maps(RESOURCE), {})
    assert user["secretary_name"] == ""
    assert user["avatar"] == ""


def test_build_context_limits_and_builds_header():
    records = [RECORD] * 5
    context = build_context(
        RESOURCE, records, PLAYER_INFO, {"char_002_amiya": "阿米娅"}
    )
    assert len(context["records"]) == 3
    assert context["season_name"] == "规程"
    assert context["version"] == "V3_1"
    assert context["phase_name"] == "序列I"
    assert context["user"]["secretary_name"] == "阿米娅"


def test_build_context_handles_empty_records():
    context = build_context(RESOURCE, [], PLAYER_INFO, {})
    assert context["records"] == []
    assert context["version"] == "V3_1"


class _FakeSkland:
    """SklandClient stand-in returning fixed garrison payloads."""

    def __init__(self):
        self.called_with: tuple[str, str] | None = None

    async def get_garrison_resource(self, cred):
        return RESOURCE

    async def get_garrison_history_log(self, cred, uid, season_id):
        self.called_with = (uid, season_id)
        return [RECORD]


@pytest.mark.anyio
async def test_garrison_client_derives_season_id():
    skland = _FakeSkland()
    client = GarrisonClient(skland)
    resource, records = await client.fetch(Credential("t", "c"), "6379755")
    assert skland.called_with == ("6379755", "act3autochess")
    assert records == [RECORD]
    assert resource is RESOURCE
