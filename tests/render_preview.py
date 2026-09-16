"""Render note.html and sanity.html with realistic fixture data for visual check."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.cards import build_note_context, build_sanity_context  # noqa: E402
from core.render import Renderer  # noqa: E402

NOW = time.time()
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
    "chars": [{"charId": f"c{i}"} for i in range(153)],
    "skins": [{"skinId": f"s{i}"} for i in range(22)],
    "charInfoMap": {
        "char_1012_skadi2": {
            "name": "浊心斯卡蒂",
            "rarity": 5,
            "profession": "WARRIOR",
        },
        "char_4009_irene": {"name": "艾丽妮", "rarity": 5, "profession": "WARRIOR"},
        "char_002_amiya": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"},
    },
    "assistChars": [
        {"charId": "char_1012_skadi2", "level": 90, "evolvePhase": 2},
        {"charId": "char_4009_irene", "level": 80, "evolvePhase": 2},
        {"charId": "char_002_amiya", "level": 50, "evolvePhase": 2},
    ],
    "routine": {
        "daily": {"current": 10, "total": 10},
        "weekly": {"current": 9, "total": 13},
    },
    "campaign": {"reward": {"current": 1200, "total": 1725}},
}


async def main() -> None:
    templates = Path(__file__).resolve().parents[1] / "templates"
    cache = Path("/tmp/akrender")
    renderer = Renderer(templates, cache, 30000)
    base_css = (templates / "base.css").read_text(encoding="utf-8")

    for template, key, context in (
        ("note.html", "note", build_note_context(PLAYER, now=NOW)),
        ("sanity.html", "sanity", build_sanity_context(PLAYER, now=NOW)),
    ):
        path = await renderer.render_html(
            template, {"base_css": base_css, "version": "0.1.0", key: context}
        )
        print(template, "->", path, path.stat().st_size if path else None)
    await renderer.close()


asyncio.run(main())
