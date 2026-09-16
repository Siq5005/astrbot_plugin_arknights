"""Builders for the daily-play cards: base, campaign, rogue, tasks, recruit.

Everything here reads the ``player/info`` payload that the plugin already
fetches, so no extra game data download is required. Name lookups that the API
does not provide (clue factions, facility labels) use fixed game constants.

This module never imports ``astrbot``.
"""

from __future__ import annotations

from typing import Any

from .assets import char_avatar
from .cards import format_remaining, format_timestamp, progress_node

# The API reports facility mood as ``ap``; a full 24 mood equals 8_640_000.
MOOD_UNIT = 360_000
MOOD_MAX = 24

# Clue factions are fixed game constants and are not returned as names.
CLUE_CN: dict[str, str] = {
    "RHODES": "罗德岛",
    "PENGUIN": "企鹅物流",
    "BLACKSTEEL": "黑钢国际",
    "GLASGOW": "格拉斯哥帮",
    "KJERAG": "喀兰贸易",
    "LATERANO": "拉特兰",
    "URSUS": "乌萨斯",
}

# Recruit slot states observed from the API. ``state`` is only a hint; the
# timestamps are authoritative, so an unknown state still renders sensibly.
RECRUIT_IDLE = 1


def mood_value(ap: Any) -> float:
    """Convert a facility mood counter into a 0-24 value.

    Args:
        ap: Raw ``ap`` field of a facility operator entry.

    Returns:
        Mood clamped to ``[0, 24]``, rounded to one decimal.
    """
    try:
        raw = float(ap or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(min(float(MOOD_MAX), max(0.0, raw / MOOD_UNIT)), 1)


def _operator_ref(char_id: str, char_info: dict[str, Any]) -> dict[str, Any]:
    """Resolve an operator id into name and avatar.

    Args:
        char_id: Internal operator id.
        char_info: The ``charInfoMap`` section.

    Returns:
        Display record for the operator.
    """
    meta = (char_info or {}).get(char_id) or {}
    return {
        "char_id": char_id,
        "name": str(meta.get("name") or char_id),
        "avatar": char_avatar(char_id) if char_id else "",
    }


def _slot(slot: dict[str, Any], char_info: dict[str, Any]) -> dict[str, Any]:
    """Normalize one facility slot.

    Args:
        slot: Raw slot entry from the ``building`` section.
        char_info: The ``charInfoMap`` section.

    Returns:
        Slot with its level and assigned operators sorted by index.
    """
    operators = []
    for item in slot.get("chars") or []:
        ref = _operator_ref(str(item.get("charId") or ""), char_info)
        mood = mood_value(item.get("ap"))
        operators.append(
            {
                **ref,
                "mood": mood,
                "mood_percent": int(mood / MOOD_MAX * 100),
                "index": int(item.get("index") or 0),
            }
        )
    operators.sort(key=lambda entry: entry["index"])
    return {"level": int(slot.get("level") or 0), "operators": operators}


def _slots_of(source: Any, char_info: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a facility entry that may be a list or a single slot."""
    if isinstance(source, list):
        return [_slot(slot, char_info) for slot in source if isinstance(slot, dict)]
    if isinstance(source, dict):
        return [_slot(source, char_info)]
    return []


def build_building_context(data: dict[str, Any]) -> dict[str, Any]:
    """Build the base (基建) card context.

    Args:
        data: The ``data`` section of a player info response.

    Returns:
        Template context for ``building.html``.
    """
    data = data or {}
    building = data.get("building") or {}
    char_info = data.get("charInfoMap") or {}

    facilities = []
    for key, label, source in (
        ("power", "发电站", "powers"),
        ("manufacture", "制造站", "manufactures"),
        ("trading", "贸易站", "tradings"),
        ("dormitory", "宿舍", "dormitories"),
        ("control", "控制中枢", "control"),
        ("meeting", "会客室", "meeting"),
    ):
        slots = _slots_of(building.get(source), char_info)
        if slots:
            facilities.append({"key": key, "name": label, "slots": slots})

    labor = building.get("labor") or {}
    labor_value = int(labor.get("value") or 0)
    labor_max = int(labor.get("maxValue") or 0)
    labor_percent = min(100, round(labor_value / labor_max * 100)) if labor_max else 0

    clue = (building.get("meeting") or {}).get("clue") or {}
    board = [CLUE_CN.get(str(item), str(item)) for item in clue.get("board") or []]

    hire = building.get("hire") or {}
    training = building.get("training") or {}
    trainee = training.get("trainee") or {}
    trainer = training.get("trainer") or {}

    return {
        "facilities": facilities,
        "labor": {
            "value": labor_value,
            "max": labor_max,
            "percent": labor_percent,
        },
        "clue": {
            "own": int(clue.get("own") or 0),
            "received": int(clue.get("received") or 0),
            "daily_reward": bool(clue.get("dailyReward")),
            "sharing": bool(clue.get("sharing")),
            "board": board,
        },
        "hire": {
            "level": int(hire.get("level") or 0),
            "refresh": int(hire.get("refreshCount") or 0),
        },
        "training": {
            "level": int(training.get("level") or 0),
            "trainee": _operator_ref(str(trainee.get("charId") or ""), char_info)[
                "name"
            ]
            if trainee
            else "",
            "trainer": _operator_ref(str(trainer.get("charId") or ""), char_info)[
                "name"
            ]
            if trainer
            else "",
        },
        "mood_max": MOOD_MAX,
    }


def build_campaign_context(data: dict[str, Any]) -> dict[str, Any]:
    """Build the annihilation (剿灭作战) card context.

    Args:
        data: The ``data`` section of a player info response.

    Returns:
        Template context for ``campaign.html``.
    """
    data = data or {}
    campaign = data.get("campaign") or {}
    info_map = data.get("campaignInfoMap") or {}
    zone_map = data.get("campaignZoneInfoMap") or {}

    records = []
    for record in campaign.get("records") or []:
        campaign_id = str(record.get("campaignId") or "")
        meta = info_map.get(campaign_id) or {}
        zone = zone_map.get(str(meta.get("campaignZoneId") or "")) or {}
        records.append(
            {
                "id": campaign_id,
                "name": str(meta.get("name") or campaign_id),
                "zone": str(zone.get("name") or ""),
                "max_kills": int(record.get("maxKills") or 0),
            }
        )
    records.sort(key=lambda item: (-item["max_kills"], item["name"]))

    cleared = sum(1 for record in records if record["max_kills"] >= 400)
    return {
        "reward": progress_node(campaign.get("reward")),
        "records": records,
        "total": len(records),
        "cleared": cleared,
    }


def build_rogue_context(data: dict[str, Any]) -> dict[str, Any]:
    """Build the integrated-strategies (集成战略) card context.

    Args:
        data: The ``data`` section of a player info response.

    Returns:
        Template context for ``rogue.html``.
    """
    data = data or {}
    rogue = data.get("rogue") or {}
    info_map = data.get("rogueInfoMap") or {}

    themes = []
    for record in rogue.get("records") or []:
        rogue_id = str(record.get("rogueId") or "")
        meta = info_map.get(rogue_id) or {}
        bank = record.get("bank") or {}
        themes.append(
            {
                "id": rogue_id,
                "name": str(meta.get("name") or rogue_id),
                "relics": int(record.get("relicCnt") or 0),
                "bank": int(bank.get("current") or 0),
                "bank_record": int(bank.get("record") or 0),
            }
        )
    return {"themes": themes}


def build_task_context(data: dict[str, Any]) -> dict[str, Any]:
    """Build the routine (任务与周常) card context.

    Args:
        data: The ``data`` section of a player info response.

    Returns:
        Template context for ``task.html``.
    """
    data = data or {}
    routine = data.get("routine") or {}
    tower = data.get("tower") or {}
    tower_reward = tower.get("reward") or {}
    return {
        "daily": progress_node(routine.get("daily")),
        "weekly": progress_node(routine.get("weekly")),
        "campaign": progress_node((data.get("campaign") or {}).get("reward")),
        "tower_lower": progress_node(tower_reward.get("lowerItem")),
        "tower_higher": progress_node(tower_reward.get("higherItem")),
        "tower_term": format_timestamp(tower_reward.get("termTs")),
    }


def _recruit_slot(slot: dict[str, Any], index: int, now: float) -> dict[str, Any]:
    """Normalize one recruitment slot.

    Args:
        slot: Raw entry from the ``recruit`` array.
        index: Zero-based slot position.
        now: Current unix timestamp.

    Returns:
        Slot with a human readable state and remaining time.
    """
    finish = int(slot.get("finishTs") or -1)
    state = int(slot.get("state") or 0)
    if finish > now:
        return {
            "index": index + 1,
            "state": "running",
            "state_cn": "招募中",
            "remaining_text": format_remaining(finish - now),
        }
    if finish > 0:
        return {
            "index": index + 1,
            "state": "done",
            "state_cn": "可领取",
            "remaining_text": "已完成",
        }
    return {
        "index": index + 1,
        "state": "idle" if state in (0, RECRUIT_IDLE) else "unknown",
        "state_cn": "空闲" if state in (0, RECRUIT_IDLE) else f"状态 {state}",
        "remaining_text": "",
    }


def build_recruit_context(
    data: dict[str, Any], now: float | None = None
) -> dict[str, Any]:
    """Build the recruitment (公开招募) card context.

    The API only exposes slot timers, not the offered tags — tags would need
    screen OCR — so this card reports slot status only.

    Args:
        data: The ``data`` section of a player info response.
        now: Current unix timestamp; defaults to the system clock.

    Returns:
        Template context for ``recruit.html``.
    """
    import time

    now = time.time() if now is None else float(now)
    slots = [
        _recruit_slot(slot, index, now)
        for index, slot in enumerate((data or {}).get("recruit") or [])
    ]
    return {
        "slots": slots,
        "running": sum(1 for slot in slots if slot["state"] == "running"),
        "ready": sum(1 for slot in slots if slot["state"] == "done"),
    }
