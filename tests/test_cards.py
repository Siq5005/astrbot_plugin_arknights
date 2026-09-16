import re

from core.cards import (
    build_note_context,
    build_sanity_context,
    format_date,
    format_remaining,
    format_stage,
    format_timestamp,
)


def test_format_remaining():
    assert format_remaining(0) == "已回满"
    assert format_remaining(-5) == "已回满"
    assert format_remaining(59) == "0分"
    assert format_remaining(3600) == "1小时0分"
    assert format_remaining(3660) == "1小时1分"
    assert format_remaining(7325) == "2小时2分"


def test_format_timestamp_and_date():
    assert format_timestamp(0) == "未知"
    assert format_timestamp(None) == "未知"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", format_timestamp(1700000000))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", format_date(1700000000))
    assert format_date(0) == "未知"


def test_format_stage():
    assert format_stage("st_09-01") == "09-01"
    assert format_stage("") == "已全部通关"
    assert format_stage(None) == "已全部通关"


def test_build_sanity_context_full():
    data = {
        "status": {
            "name": "探姬",
            "ap": {"current": 100, "max": 135, "completeRecoveryTime": -1},
            "storeTs": 1700000000,
        }
    }
    ctx = build_sanity_context(data, now=1_000_000.0)
    assert ctx["current"] == 135
    assert ctx["max"] == 135
    assert ctx["full"] is True
    assert ctx["remaining_text"] == "已回满"
    assert ctx["percent"] == 100
    assert ctx["nickname"] == "探姬"


def test_build_sanity_context_recovering():
    now = 1_000_000.0
    data = {
        "status": {
            "ap": {"current": 1, "max": 135, "completeRecoveryTime": int(now + 3600)}
        }
    }
    ctx = build_sanity_context(data, now=now)
    assert ctx["current"] == 125
    assert ctx["full"] is False
    assert ctx["remaining_text"] == "1小时0分"
    assert ctx["percent"] == 93


def test_build_sanity_context_handles_empty_data():
    ctx = build_sanity_context({}, now=1_000_000.0)
    assert ctx["current"] == 0
    assert ctx["max"] == 0
    assert ctx["percent"] == 0
    assert ctx["remaining_text"] == "已回满"


def test_build_note_context_falls_back_to_list_lengths():
    data = {
        "status": {
            "name": "探姬",
            "level": 71,
            "charCnt": 0,
            "skinCnt": 0,
            "registerTs": 1556736265,
            "storeTs": 1668502681,
            "mainStageProgress": "st_09-01",
        },
        "chars": [{"charId": "a"}, {"charId": "b"}],
        "skins": [{"skinId": "s1"}],
        "charInfoMap": {"a": {"name": "A", "rarity": 4}},
        "assistChars": [
            {"charId": "a", "level": 90, "evolvePhase": 2, "potentialRank": 5},
            {"charId": "unknown", "level": 1, "evolvePhase": 0},
        ],
        "routine": {
            "daily": {"current": 3, "total": 10},
            "weekly": {"current": 5, "total": 13},
        },
        "campaign": {"reward": {"current": 300, "total": 1725}},
    }
    ctx = build_note_context(data, now=1_000_000.0)
    assert ctx["char_count"] == 2
    assert ctx["skin_count"] == 1
    assert ctx["level"] == 71
    assert ctx["main_stage"] == "09-01"
    assert ctx["daily"] == {"current": 3, "total": 10, "percent": 30}
    assert ctx["weekly"] == {"current": 5, "total": 13, "percent": 38}
    assert ctx["campaign"] == {"current": 300, "total": 1725, "percent": 17}
    assert ctx["assist"][0]["name"] == "A"
    assert ctx["assist"][0]["stars"] == 5
    assert ctx["assist"][0]["avatar"].endswith("/char_avatar/a.png")
    # unknown char ids fall back to showing the raw id, but the avatar URL is
    # still derived from the char id because assets are keyed by it
    assert ctx["assist"][1]["name"] == "unknown"
    assert ctx["assist"][1]["avatar"].endswith("/char_avatar/unknown.png")
    assert ctx["secretary"]["stars"] == 1


def test_build_note_context_handles_empty_data():
    ctx = build_note_context({}, now=1_000_000.0)
    assert ctx["char_count"] == 0
    assert ctx["assist"] == []
    assert ctx["daily"]["percent"] == 0
