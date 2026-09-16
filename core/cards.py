"""Pure builders that turn Skland payloads into template context.

Keeping these separate from ``main.py`` means the presentation logic can be unit
tested, and it keeps every ``core`` module free of AstrBot imports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .assets import char_avatar
from .skland import SANITY_SECONDS_PER_POINT, derive_sanity

UNKNOWN_TEXT = "未知"


def format_timestamp(value: Any) -> str:
    """Format a unix timestamp as a local ``YYYY-MM-DD HH:MM`` string.

    Args:
        value: Unix timestamp; falsy or invalid values yield ``"未知"``.

    Returns:
        Formatted timestamp or ``"未知"``.
    """
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return UNKNOWN_TEXT
    if seconds <= 0:
        return UNKNOWN_TEXT
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return UNKNOWN_TEXT


def format_date(value: Any) -> str:
    """Format a unix timestamp as a local ``YYYY-MM-DD`` string.

    Args:
        value: Unix timestamp.

    Returns:
        Formatted date or ``"未知"``.
    """
    formatted = format_timestamp(value)
    return formatted if formatted == UNKNOWN_TEXT else formatted[:10]


def format_remaining(seconds: Any) -> str:
    """Describe a remaining duration in Chinese.

    Args:
        seconds: Remaining seconds.

    Returns:
        ``"已回满"`` when no time is left, otherwise ``"X小时Y分"`` or ``"Y分"``.
    """
    try:
        remaining = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        remaining = 0
    if remaining <= 0:
        return "已回满"
    hours, rest = divmod(remaining, 3600)
    minutes = rest // 60
    return f"{hours}小时{minutes}分" if hours else f"{minutes}分"


def format_stage(value: Any) -> str:
    """Format the main story progress marker.

    Args:
        value: Raw ``mainStageProgress`` value from the API.

    Returns:
        The stage number, or ``"已全部通关"`` when the field is empty (the API
        omits it once the main story is complete).
    """
    text = str(value or "").strip()
    if not text:
        return "已全部通关"
    return text[3:] if text.startswith("st_") else text


def _progress(node: Any) -> dict[str, int]:
    """Normalize a ``{current, total}`` progress node.

    Args:
        node: Raw progress mapping from the API.

    Returns:
        Normalized mapping including a rounded ``percent``.
    """
    node = node if isinstance(node, dict) else {}
    current = int(node.get("current") or 0)
    total = int(node.get("total") or 0)
    percent = min(100, round(current / total * 100)) if total else 0
    return {"current": current, "total": total, "percent": percent}


def build_sanity_context(
    data: dict[str, Any], now: float | None = None
) -> dict[str, Any]:
    """Build the sanity card context.

    Args:
        data: The ``data`` section of a player info response.
        now: Current unix timestamp; defaults to the system clock.

    Returns:
        Template context for ``sanity.html``.
    """
    import time

    now = time.time() if now is None else float(now)
    status = (data or {}).get("status") or {}
    ap = status.get("ap") or {}
    max_ap = int(ap.get("max") or 0)
    recovery = int(ap.get("completeRecoveryTime") or 0)
    current = derive_sanity(
        ap.get("current"), max_ap, recovery, SANITY_SECONDS_PER_POINT, now
    )
    full = recovery <= now or current >= max_ap
    remaining = 0 if full else max(0, recovery - int(now))
    percent = min(100, round(current / max_ap * 100)) if max_ap else 0
    return {
        "nickname": status.get("name") or "",
        "current": current,
        "max": max_ap,
        "percent": percent,
        "full": full,
        "remaining_text": "已回满" if full else format_remaining(remaining),
        "recovery_minutes": SANITY_SECONDS_PER_POINT // 60,
        "data_time": format_timestamp(status.get("storeTs")),
    }


def build_note_context(
    data: dict[str, Any], now: float | None = None
) -> dict[str, Any]:
    """Build the account overview card context.

    Args:
        data: The ``data`` section of a player info response.
        now: Current unix timestamp; defaults to the system clock.

    Returns:
        Template context for ``note.html``.
    """
    data = data or {}
    status = data.get("status") or {}
    char_info = data.get("charInfoMap") or {}
    chars = data.get("chars") or []
    skins = data.get("skins") or []
    routine = data.get("routine") or {}

    assist = []
    for item in data.get("assistChars") or []:
        char_id = str(item.get("charId") or "")
        info = char_info.get(char_id) or {}
        assist.append(
            {
                "char_id": char_id,
                "name": info.get("name") or char_id,
                "level": int(item.get("level") or 0),
                "elite": int(item.get("evolvePhase") or 0),
                "stars": int(info.get("rarity") or 0) + 1,
                "avatar": char_avatar(char_id) if char_id else "",
            }
        )

    return {
        "nickname": status.get("name") or "",
        "level": int(status.get("level") or 0),
        "register_date": format_date(status.get("registerTs")),
        "main_stage": format_stage(status.get("mainStageProgress")),
        # charCnt/skinCnt are unreliable (observed as 0), so prefer the list sizes.
        "char_count": int(status.get("charCnt") or 0) or len(chars),
        "skin_count": int(status.get("skinCnt") or 0) or len(skins),
        "assist": assist,
        "sanity": build_sanity_context(data, now),
        "daily": _progress(routine.get("daily")),
        "weekly": _progress(routine.get("weekly")),
        "campaign": _progress((data.get("campaign") or {}).get("reward")),
        "data_time": format_timestamp(status.get("storeTs")),
    }
