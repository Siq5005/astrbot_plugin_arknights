import time

from core.daily import (
    build_building_context,
    build_campaign_context,
    build_recruit_context,
    build_rogue_context,
    build_task_context,
    mood_value,
)

CHAR_INFO = {
    "char_002_amiya": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"},
    "char_1012_skadi2": {"name": "浊心斯卡蒂", "rarity": 5, "profession": "WARRIOR"},
}


def test_mood_value_scales_and_clamps():
    assert mood_value(8_640_000) == 24.0
    assert mood_value(0) == 0.0
    assert mood_value(None) == 0.0
    assert mood_value("bad") == 0.0
    assert mood_value(1_800_000) == 5.0
    # never exceeds the cap
    assert mood_value(99_999_999) == 24.0


def test_build_building_context_normalizes_facilities():
    data = {
        "charInfoMap": CHAR_INFO,
        "building": {
            "powers": [
                {
                    "slotId": "s1",
                    "level": 3,
                    "chars": [
                        {"charId": "char_002_amiya", "ap": 8_640_000, "index": 0}
                    ],
                }
            ],
            "manufactures": [{"slotId": "s2", "level": 3, "chars": []}],
            "tradings": [{"slotId": "s3", "level": 2, "chars": []}],
            "dormitories": [{"slotId": "s4", "level": 5, "chars": []}],
            "control": {"slotId": "s5", "level": 5, "chars": []},
            "meeting": {
                "slotId": "s6",
                "level": 3,
                "chars": [],
                "clue": {
                    "own": 10,
                    "received": 2,
                    "dailyReward": True,
                    "sharing": False,
                    "board": ["PENGUIN", "UNKNOWN_FACTION"],
                },
            },
            "labor": {"value": 150, "maxValue": 200},
            "hire": {"level": 3, "refreshCount": 4},
            "training": {
                "level": 3,
                "trainee": {"charId": "char_1012_skadi2"},
                "trainer": {"charId": "char_002_amiya"},
            },
        },
    }
    ctx = build_building_context(data)
    names = [facility["name"] for facility in ctx["facilities"]]
    assert names == ["发电站", "制造站", "贸易站", "宿舍", "控制中枢", "会客室"]
    power = ctx["facilities"][0]
    assert power["slots"][0]["level"] == 3
    assert power["slots"][0]["operators"][0]["name"] == "阿米娅"
    assert power["slots"][0]["operators"][0]["stars"] == 5
    assert power["slots"][0]["operators"][0]["mood"] == 24.0
    assert power["slots"][0]["operators"][0]["mood_percent"] == 100
    assert ctx["labor"] == {"value": 150, "max": 200, "percent": 75}
    # known factions are translated, unknown ones are passed through
    assert ctx["clue"]["board"] == ["企鹅物流", "UNKNOWN_FACTION"]
    assert ctx["clue"]["daily_reward"] is True
    assert ctx["hire"]["refresh"] == 4
    assert ctx["training"]["trainee"] == "浊心斯卡蒂"
    assert ctx["training"]["trainer"] == "阿米娅"


def test_build_building_context_handles_empty_data():
    ctx = build_building_context({})
    assert ctx["facilities"] == []
    assert ctx["labor"]["percent"] == 0
    assert ctx["clue"]["board"] == []
    assert ctx["training"]["trainee"] == ""


def test_build_campaign_context_uses_name_maps_and_sorts():
    data = {
        "campaign": {
            "reward": {"current": 1200, "total": 1725},
            "records": [
                {"campaignId": "camp_02", "maxKills": 100},
                {"campaignId": "camp_01", "maxKills": 400},
                {"campaignId": "camp_missing", "maxKills": 250},
            ],
        },
        "campaignInfoMap": {
            "camp_01": {"name": "切尔诺伯格", "campaignZoneId": "camp_zone_3"},
            "camp_02": {"name": "龙门外环", "campaignZoneId": "camp_zone_1"},
        },
        "campaignZoneInfoMap": {
            "camp_zone_3": {"name": "乌萨斯"},
            "camp_zone_1": {"name": "炎国龙门"},
        },
    }
    ctx = build_campaign_context(data)
    assert ctx["reward"] == {"current": 1200, "total": 1725, "percent": 70}
    assert [record["name"] for record in ctx["records"]] == [
        "切尔诺伯格",
        "camp_missing",
        "龙门外环",
    ]
    assert ctx["records"][0]["zone"] == "乌萨斯"
    # unknown ids fall back to the raw id rather than disappearing
    assert ctx["records"][1]["name"] == "camp_missing"
    assert ctx["total"] == 3
    assert ctx["cleared"] == 1


def test_build_rogue_context_resolves_theme_names():
    data = {
        "rogue": {
            "records": [
                {
                    "rogueId": "rogue_1",
                    "relicCnt": 86,
                    "bank": {"current": 798, "record": 900},
                },
                {"rogueId": "rogue_2", "relicCnt": 0, "bank": {}},
            ]
        },
        "rogueInfoMap": {"rogue_1": {"name": "傀影与猩红孤钻"}},
    }
    ctx = build_rogue_context(data)
    assert ctx["themes"][0] == {
        "id": "rogue_1",
        "name": "傀影与猩红孤钻",
        "relics": 86,
        "bank": 798,
        "bank_record": 900,
    }
    assert ctx["themes"][1]["name"] == "rogue_2"
    assert ctx["themes"][1]["bank"] == 0


def test_build_task_context():
    data = {
        "routine": {
            "daily": {"current": 8, "total": 10},
            "weekly": {"current": 5, "total": 13},
        },
        "campaign": {"reward": {"current": 300, "total": 1725}},
        "tower": {
            "reward": {
                "lowerItem": {"current": 30, "total": 60},
                "higherItem": {"current": 6, "total": 24},
                "termTs": 1700000000,
            }
        },
    }
    ctx = build_task_context(data)
    assert ctx["daily"] == {"current": 8, "total": 10, "percent": 80}
    assert ctx["weekly"]["percent"] == 38
    assert ctx["campaign"]["percent"] == 17
    assert ctx["tower_lower"]["percent"] == 50
    assert ctx["tower_higher"]["percent"] == 25
    assert ctx["tower_term"] != "未知"


def test_build_recruit_context_states():
    now = 1_000_000.0
    data = {
        "recruit": [
            {"startTs": -1, "finishTs": -1, "state": 1},
            {"startTs": 1, "finishTs": int(now + 1800), "state": 2},
            {"startTs": 1, "finishTs": int(now - 60), "state": 2},
        ]
    }
    ctx = build_recruit_context(data, now=now)
    assert [slot["state"] for slot in ctx["slots"]] == ["idle", "running", "done"]
    assert ctx["slots"][0]["state_cn"] == "空闲"
    assert ctx["slots"][1]["remaining_text"] == "30分"
    assert ctx["slots"][2]["remaining_text"] == "已完成"
    assert ctx["running"] == 1
    assert ctx["ready"] == 1


def test_build_recruit_context_empty():
    ctx = build_recruit_context({}, now=time.time())
    assert ctx["slots"] == []
    assert ctx["running"] == 0
