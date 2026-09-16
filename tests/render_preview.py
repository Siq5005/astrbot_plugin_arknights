"""Render every card template with realistic fixture data for visual checks."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.cards import build_note_context, build_sanity_context  # noqa: E402
from core.daily import (  # noqa: E402
    build_building_context,
    build_campaign_context,
    build_recruit_context,
    build_rogue_context,
    build_task_context,
)
from core.operators import (  # noqa: E402
    build_operator_context,
    build_roster_context,
    find_operator,
    group_operators,
)
from core.render import Renderer  # noqa: E402

NOW = time.time()

OPERATORS = [
    ("char_002_amiya", "阿米娅", 4, "CASTER", 90, 2, 5, 200),
    ("char_003_kalts", "凯尔希", 5, "MEDIC", 90, 2, 4, 200),
    ("char_1012_skadi2", "浊心斯卡蒂", 5, "WARRIOR", 90, 2, 3, 145),
    ("char_4009_irene", "艾丽妮", 5, "WARRIOR", 80, 2, 1, 88),
    ("char_198_blackd", "黑角", 0, "TANK", 30, 0, 2, 45),
    ("char_208_melan", "玫兰莎", 0, "WARRIOR", 40, 1, 1, 60),
    ("char_4055_bgsnow", "鸿雪", 5, "SNIPER", 90, 2, 2, 120),
    ("char_1024_hbisc2", "迷迭香", 5, "SUPPORT", 70, 2, 0, 30),
    ("char_1013_chen2", "陈", 5, "WARRIOR", 85, 2, 3, 160),
    ("char_436_whispr", "晓歌", 5, "PIONEER", 60, 2, 1, 75),
    ("char_1001_amiya2", "近卫阿米娅", 4, "SPECIAL", 90, 2, 5, 200),
    ("char_009_12fce", "12F", 0, "CASTER", 40, 1, 3, 55),
]

CHAR_INFO = {
    cid: {"name": name, "rarity": rarity, "profession": profession}
    for cid, name, rarity, profession, *_ in OPERATORS
}

CHARS = [
    {
        "charId": cid,
        "level": level,
        "evolvePhase": elite,
        "potentialRank": potential,
        "favorPercent": favor,
        "defaultSkillId": "skchr_amiya_3",
        "skills": [
            {"id": "skchr_amiya_2", "specializeLevel": 0},
            {"id": "skchr_amiya_3", "specializeLevel": 3},
        ],
        "equip": [{"id": "uniequip_002_amiya", "level": 1}],
    }
    for cid, _name, _rarity, _profession, level, elite, potential, favor in OPERATORS
]

PLAYER = {
    "status": {
        "name": "探姬#9315",
        "level": 71,
        "registerTs": 1556736265,
        "mainStageProgress": "st_09-01",
        "storeTs": int(NOW) - 900,
        "charCnt": 0,
        "skinCnt": 0,
        "resume": "罗德岛终端测试签名 —— 数据来自森空岛官方接口的快照。",
        "secretary": {"charId": "char_1012_skadi2", "skinId": "char_1012_skadi2#2"},
        "ap": {"current": 88, "max": 135, "completeRecoveryTime": int(NOW) + 4200},
    },
    "chars": CHARS,
    "skins": [{"skinId": f"s{i}"} for i in range(22)],
    "charInfoMap": CHAR_INFO,
    "equipmentInfoMap": {"uniequip_002_amiya": {"name": "阿米娅证章"}},
    "assistChars": [
        {"charId": "char_1012_skadi2", "level": 90, "evolvePhase": 2},
        {"charId": "char_4009_irene", "level": 80, "evolvePhase": 2},
        {"charId": "char_002_amiya", "level": 90, "evolvePhase": 2},
    ],
    "routine": {
        "daily": {"current": 10, "total": 10},
        "weekly": {"current": 9, "total": 13},
    },
    "campaign": {
        "reward": {"current": 1200, "total": 1725},
        "records": [
            {"campaignId": "camp_01", "maxKills": 400},
            {"campaignId": "camp_02", "maxKills": 271},
            {"campaignId": "camp_r_05", "maxKills": 400},
            {"campaignId": "camp_r_07", "maxKills": 288},
        ],
    },
    "campaignInfoMap": {
        "camp_01": {"name": "切尔诺伯格", "campaignZoneId": "camp_zone_3"},
        "camp_02": {"name": "龙门外环", "campaignZoneId": "camp_zone_1"},
        "camp_r_05": {"name": "潮汐作战", "campaignZoneId": "camp_zone_10"},
        "camp_r_07": {"name": "风蚀高地", "campaignZoneId": "camp_zone_10"},
    },
    "campaignZoneInfoMap": {
        "camp_zone_3": {"name": "乌萨斯"},
        "camp_zone_1": {"name": "炎国龙门"},
        "camp_zone_10": {"name": "维多利亚"},
    },
    "rogue": {
        "records": [
            {
                "rogueId": "rogue_1",
                "relicCnt": 86,
                "bank": {"current": 798, "record": 900},
            },
            {
                "rogueId": "rogue_2",
                "relicCnt": 42,
                "bank": {"current": 310, "record": 500},
            },
        ]
    },
    "rogueInfoMap": {
        "rogue_1": {"name": "傀影与猩红孤钻"},
        "rogue_2": {"name": "水月与深蓝之树"},
    },
    "tower": {
        "reward": {
            "lowerItem": {"current": 30, "total": 60},
            "higherItem": {"current": 6, "total": 24},
            "termTs": 1694807999,
        }
    },
    "recruit": [
        {"startTs": -1, "finishTs": -1, "state": 1},
        {"startTs": 1, "finishTs": int(NOW + 5400), "state": 2},
        {"startTs": 1, "finishTs": int(NOW - 120), "state": 2},
        {"startTs": -1, "finishTs": -1, "state": 1},
    ],
    "building": {
        "powers": [
            {
                "slotId": "slot_26",
                "level": 3,
                "chars": [{"charId": "char_1012_skadi2", "ap": 8_640_000, "index": 0}],
            },
            {
                "slotId": "slot_16",
                "level": 3,
                "chars": [{"charId": "char_4055_bgsnow", "ap": 4_320_000, "index": 0}],
            },
        ],
        "manufactures": [
            {
                "slotId": "slot_14",
                "level": 3,
                "chars": [
                    {"charId": "char_1013_chen2", "ap": 1_800_000, "index": 0},
                    {"charId": "char_002_amiya", "ap": 7_200_000, "index": 1},
                ],
            }
        ],
        "tradings": [
            {
                "slotId": "slot_24",
                "level": 3,
                "chars": [
                    {"charId": "char_198_blackd", "ap": 2_160_000, "index": 0},
                ],
            }
        ],
        "dormitories": [
            {
                "slotId": "slot_28",
                "level": 5,
                "chars": [{"charId": "char_003_kalts", "ap": 8_640_000, "index": 0}],
            }
        ],
        "control": {
            "slotId": "slot_34",
            "level": 5,
            "chars": [{"charId": "char_4009_irene", "ap": 6_480_000, "index": 0}],
        },
        "meeting": {
            "slotId": "slot_36",
            "level": 3,
            "chars": [{"charId": "char_436_whispr", "ap": 8_640_000, "index": 0}],
            "clue": {
                "own": 10,
                "received": 2,
                "dailyReward": True,
                "sharing": False,
                "board": ["PENGUIN", "GLASGOW", "KJERAG", "BLACKSTEEL", "RHODES"],
            },
        },
        "labor": {"value": 152, "maxValue": 200},
        "hire": {"level": 3, "refreshCount": 4},
        "training": {
            "level": 3,
            "trainee": {"charId": "char_1012_skadi2"},
            "trainer": {"charId": "char_003_kalts"},
        },
    },
}


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    templates = root / "templates"
    renderer = Renderer(templates, Path("/tmp/akrender"), 30000)
    base_css = (templates / "base.css").read_text(encoding="utf-8")

    note = build_note_context(PLAYER, now=NOW)
    sanity = build_sanity_context(PLAYER, now=NOW)
    groups = group_operators(PLAYER["chars"], CHAR_INFO)
    roster = build_roster_context(groups, CHAR_INFO)
    operator = find_operator(PLAYER["chars"], CHAR_INFO, "阿米娅")
    detail = build_operator_context(operator, PLAYER["equipmentInfoMap"])

    cards = [
        ("note.html", "note", note),
        ("sanity.html", "sanity", sanity),
        ("operator_list.html", "roster", roster),
        ("operator.html", "op", detail),
        ("building.html", "building", build_building_context(PLAYER)),
        ("campaign.html", "campaign", build_campaign_context(PLAYER)),
        ("rogue.html", "rogue", build_rogue_context(PLAYER)),
        ("task.html", "task", build_task_context(PLAYER)),
        ("recruit.html", "recruit", build_recruit_context(PLAYER, now=NOW)),
    ]
    for template, key, context in cards:
        path = await renderer.render_html(
            template, {"base_css": base_css, "version": "0.1.0", key: context}
        )
        print(f"{template} -> {path} ({path.stat().st_size if path else 0} bytes)")
    await renderer.close()


asyncio.run(main())
