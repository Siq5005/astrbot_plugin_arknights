"""Garrison protocol (卫戍协议) battle-record query.

The module has two halves, mirroring ``core/gacha.py``:

* Pure mapping and context builders that shape the ``guide/resource`` and
  ``history-log`` payloads into template data. They take plain dicts so they can
  be unit tested against captured payloads.
* :class:`GarrisonClient`, which fetches the two signed endpoints through a
  :class:`~core.skland.SklandClient`.

This module never imports ``astrbot``; the display names come straight from the
payloads and the plugin's own character table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .skland import Credential, SklandClient

# Display label tables, read out of the official guide tool's bundle.
MODE_LABELS = {"MULTI": "联合模拟", "SINGLE": "独立模拟", "LOCAL": "本地模拟"}
DIFFICULTY_LABELS = {
    "FUNNY": "标准模拟",
    "NORMAL": "险境模拟",
    "HARD": "绝境模拟",
    "ABYSS": "终极模拟",
}

# ``chessLevel`` is 1..6; index 0 holds the fallback for a missing level.
ROMAN = ("0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII")

MAX_RECORDS = 3


class GarrisonError(Exception):
    """Raised when a garrison query cannot produce a result."""


def mode_label(value: Any) -> str:
    """Map a ``modeType`` code to its display label.

    Args:
        value: Raw ``modeType`` value.

    Returns:
        The label, the raw value when unknown, or ``"-"`` when empty.
    """
    return MODE_LABELS.get(str(value or ""), str(value or "") or "-")


def difficulty_label(value: Any) -> str:
    """Map a ``modeDifficulty`` code to its display label.

    Args:
        value: Raw ``modeDifficulty`` value.

    Returns:
        The label, the raw value when unknown, or ``"-"`` when empty.
    """
    return DIFFICULTY_LABELS.get(str(value or ""), str(value or "") or "-")


def roman_level(value: Any) -> str:
    """Render a chess level as a Roman numeral.

    Args:
        value: ``chessLevel`` value.

    Returns:
        Roman numeral clamped to the supported range, ``"0"`` when absent.
    """
    try:
        level = int(value or 0)
    except (TypeError, ValueError):
        level = 0
    return ROMAN[min(max(level, 0), len(ROMAN) - 1)]


def format_ts(value: Any) -> str:
    """Format a unix timestamp as a short local ``MM-DD HH:MM`` string.

    Args:
        value: Unix timestamp; invalid values yield ``"-"``.

    Returns:
        Formatted timestamp or ``"-"``.
    """
    try:
        return datetime.fromtimestamp(int(value)).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "-"


def build_maps(resource: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index the guide resource so ids can be shown as names.

    Args:
        resource: The ``guide/resource`` ``data`` payload.

    Returns:
        Mapping with ``bands``, ``bonds``, ``chars`` and ``items`` keyed by id.
    """
    resource = resource or {}

    def index(items: Any, key: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for item in items or []:
            if isinstance(item, dict) and item.get(key):
                out[str(item[key])] = item
        return out

    return {
        "bands": index(resource.get("strategies"), "strategyId"),
        "bonds": index(resource.get("bonds"), "bondId"),
        "chars": index(resource.get("chars"), "charId"),
        "items": index(resource.get("items"), "itemId"),
    }


def pick_char(maps: dict[str, Any], chess: dict[str, Any]) -> dict[str, Any]:
    """Resolve a chess piece to its portrait, Roman level and equip icons.

    ``chessInfo`` already carries ``charId`` and ``charName``; the resource only
    supplies the portrait and the equip icons.

    Args:
        maps: Indexed resource tables from :func:`build_maps`.
        chess: One ``chessSquad`` entry.

    Returns:
        Template-ready unit with ``avatar``, ``roman``, ``level`` and ``equips``.
    """
    chess = chess or {}
    info = chess.get("chessInfo") or {}
    char_id = str(info.get("charId") or chess.get("charId") or "")
    char = maps["chars"].get(char_id, {})
    equips = []
    for equip in chess.get("equips") or []:
        raw = maps["items"].get(str(equip.get("equipId") or ""), {})
        icon = str(raw.get("iconUrl") or "")
        if icon:
            equips.append({"icon": icon})
    # ``chessLevel`` comes from the payload, so treat it like ``roman_level``
    # does: a non-numeric value must not raise outside the command's guard.
    try:
        level = int(info.get("chessLevel") or 0)
    except (TypeError, ValueError):
        level = 0
    return {
        "name": str(info.get("charName") or char.get("name") or char_id),
        "avatar": str(char.get("avatarUrl") or char.get("halfBodyUrl") or ""),
        "roman": roman_level(level),
        "level": level,
        "equips": equips,
    }


def _duration(end_ts: Any, start_ts: Any) -> str:
    """Format the game duration from its unix timestamps.

    Args:
        end_ts: ``gameEndTs``.
        start_ts: ``gameStartTs``.

    Returns:
        ``"X分YY秒"``, or ``"-"`` when the timestamps are unusable.
    """
    try:
        seconds = max(0, int(end_ts or 0) - int(start_ts or 0))
    except (TypeError, ValueError):
        return "-"
    return f"{seconds // 60}分{seconds % 60:02d}秒" if seconds else "-"


def prepare_record(record: dict[str, Any], maps: dict[str, Any]) -> dict[str, Any]:
    """Shape one history record for the template.

    Args:
        record: One ``data.records`` entry.
        maps: Indexed resource tables from :func:`build_maps`.

    Returns:
        Template-ready game with badge, mode, strategy, squad, bonds and footer.
    """
    band = maps["bands"].get(str(record.get("bandId") or ""), {})
    bonds = []
    for bond in record.get("bondInfo") or []:
        raw = maps["bonds"].get(str(bond.get("bondId") or ""), {})
        bonds.append(
            {
                "name": str(raw.get("name") or bond.get("bondId") or ""),
                "icon": str(raw.get("iconUrl") or ""),
                "layer": bond.get("layer") or 0,
                "activate": bool(bond.get("activate")),
            }
        )
    bonds.sort(key=lambda item: (-item["activate"], -item["layer"]))

    squad = [pick_char(maps, chess) for chess in record.get("chessSquad") or []]
    squad.sort(key=lambda unit: -unit["level"])

    success = int(record.get("completeState") or 0) == 1
    return {
        "success": success,
        # The badge always states the outcome; the payload's ``title`` is empty
        # in practice and must never replace it.
        "title": "模拟成功" if success else "模拟失败",
        "pass_round": record.get("passRound") or 0,
        "mode": mode_label(record.get("modeType")),
        "band_icon": str(band.get("iconUrl") or ""),
        "strategy_name": str(band.get("name") or record.get("bandId") or ""),
        "difficulty": difficulty_label(record.get("modeDifficulty")),
        "version": str(record.get("versionId") or ""),
        "start": format_ts(record.get("gameStartTs")),
        "duration": _duration(record.get("gameEndTs"), record.get("gameStartTs")),
        "trophy_before": record.get("trophyBefore"),
        "trophy_after": record.get("trophyAfter"),
        "kill_cnt": record.get("killCnt"),
        "coin_cost": record.get("coinCost"),
        "squad": squad,
        "bonds": bonds,
    }


def build_user(
    player_info: dict[str, Any] | None,
    maps: dict[str, Any],
    char_names: dict[str, str] | None,
) -> dict[str, Any]:
    """Build the account header from the ``player/info`` payload.

    The assistant operator name prefers the guide resource, then falls back to
    the plugin's own character table because basic operators such as Amiya are
    absent from the guide.

    Args:
        player_info: The ``player/info`` ``data`` payload.
        maps: Indexed resource tables from :func:`build_maps`.
        char_names: ``id -> name`` table from ``core.gamedata``.

    Returns:
        Template-ready user bar.
    """
    status = (player_info or {}).get("status") or {}
    secretary = status.get("secretary") or {}
    char_id = str(secretary.get("charId") or "")
    char = maps["chars"].get(char_id, {})
    char_names = char_names or {}
    return {
        "uid": str(status.get("uid") or ""),
        "name": str(status.get("name") or ""),
        "level": status.get("level") or "",
        "avatar": (status.get("avatar") or {}).get("url") or "",
        "secretary_name": str(char.get("name") or char_names.get(char_id) or char_id),
        "secretary_icon": str(char.get("avatarUrl") or ""),
    }


def build_context(
    resource: dict[str, Any] | None,
    records: list[dict[str, Any]] | None,
    player_info: dict[str, Any] | None,
    char_names: dict[str, str] | None,
    limit: int = MAX_RECORDS,
) -> dict[str, Any]:
    """Build the template context for the recent-games card.

    Args:
        resource: The ``guide/resource`` ``data`` payload.
        records: The ``history-log`` records, newest first.
        player_info: The ``player/info`` ``data`` payload.
        char_names: ``id -> name`` table from ``core.gamedata``.
        limit: Maximum number of games to show.

    Returns:
        Context dict with ``season_name``, ``version``, ``phase_name``, ``user``
        and ``records``.
    """
    maps = build_maps(resource)
    seasons = (resource or {}).get("seasons") or []
    season = seasons[0] if seasons else {}
    version_info = (resource or {}).get("versionInfo") or {}
    records_shaped = [
        prepare_record(record, maps) for record in (records or [])[:limit]
    ]
    version = str(version_info.get("versionId") or "")
    if not version and records_shaped:
        version = str(records_shaped[0].get("version") or "")
    return {
        "season_name": str(season.get("name") or ""),
        "version": version or "-",
        "phase_name": str(version_info.get("phaseName") or ""),
        "user": build_user(player_info, maps, char_names),
        # Keyed "records" rather than "items" because Jinja resolves
        # ``garrison.items`` to the dict's own ``.items`` method.
        "records": records_shaped,
    }


class GarrisonClient:
    """Fetches garrison resource and history through a ``SklandClient``."""

    def __init__(self, skland: SklandClient) -> None:
        """Initialize the client.

        Args:
            skland: Shared Skland client used for the signed requests.
        """
        self.skland = skland

    async def fetch(
        self, cred: Credential, uid: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Fetch the guide resource and the role's recent history.

        Args:
            cred: Skland credential pair.
            uid: Role uid.

        Returns:
            Pair of the guide ``resource`` payload and the history ``records``.

        Raises:
            GarrisonError: When the guide reports no active season.
            SklandError: When a signed request fails.
        """
        resource = await self.skland.get_garrison_resource(cred)
        seasons = resource.get("seasons") or []
        season_id = str(seasons[0].get("seasonId") or "") if seasons else ""
        if not season_id:
            raise GarrisonError("未查询到卫戍协议赛季信息")
        records = await self.skland.get_garrison_history_log(cred, uid, season_id)
        return resource, records
