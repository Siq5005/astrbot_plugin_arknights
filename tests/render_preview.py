"""Render every card template with realistic fixture data for visual checks."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.cards import build_note_context, build_sanity_context  # noqa: E402
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
    "campaign": {"reward": {"current": 1200, "total": 1725}},
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
    ]
    for template, key, context in cards:
        path = await renderer.render_html(
            template, {"base_css": base_css, "version": "0.1.0", key: context}
        )
        print(f"{template} -> {path} ({path.stat().st_size if path else 0} bytes)")
    await renderer.close()


asyncio.run(main())
