"""Operator roster grouping and lookup.

All operator metadata comes from the ``charInfoMap`` section of the Skland
player info payload, so no bundled game data table is needed: names, rarity and
profession are already present there.
"""

from __future__ import annotations

from typing import Any

from .assets import char_avatar, char_portrait, skill_icon

# Display order is significant: the roster card renders professions in this order.
PROFESSION_CN: dict[str, str] = {
    "PIONEER": "先锋",
    "WARRIOR": "近卫",
    "SNIPER": "狙击",
    "CASTER": "术师",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "TANK": "重装",
    "SPECIAL": "特种",
}

UNKNOWN_PROFESSION_CN = "其他"


def _operator_entry(char: dict[str, Any], char_info: dict[str, Any]) -> dict[str, Any]:
    """Build the display record for one owned operator.

    Args:
        char: Entry from the ``chars`` array.
        char_info: The full ``charInfoMap``.

    Returns:
        Normalized operator record used by the templates.
    """
    char_id = str(char.get("charId") or "")
    meta = char_info.get(char_id) or {}
    profession = str(meta.get("profession") or "")
    return {
        "char_id": char_id,
        "name": str(meta.get("name") or char_id),
        "profession": profession,
        "profession_cn": PROFESSION_CN.get(profession, UNKNOWN_PROFESSION_CN),
        # charInfoMap rarity is zero based; stars are what players expect.
        "stars": int(meta.get("rarity") or 0) + 1,
        "level": int(char.get("level") or 0),
        "elite": int(char.get("evolvePhase") or 0),
        "potential": int(char.get("potentialRank") or 0),
        "favor": int(char.get("favorPercent") or 0),
        "avatar": char_avatar(char_id) if char_id else "",
        "skills": list(char.get("skills") or []),
        "equip": list(char.get("equip") or []),
        "default_skill_id": str(char.get("defaultSkillId") or ""),
    }


def group_operators(
    chars: list[dict[str, Any]], char_info: dict[str, Any]
) -> list[dict[str, Any]]:
    """Group owned operators by profession for the roster card.

    Args:
        chars: The ``chars`` array from the player info payload.
        char_info: The ``charInfoMap`` section.

    Returns:
        Non-empty profession groups in the fixed :data:`PROFESSION_CN` order,
        each sorted by descending rarity then name. Operators missing from
        ``charInfoMap`` are skipped.
    """
    char_info = char_info or {}
    buckets: dict[str, list[dict[str, Any]]] = {}
    for char in chars or []:
        char_id = str(char.get("charId") or "")
        if char_id not in char_info:
            continue
        entry = _operator_entry(char, char_info)
        buckets.setdefault(entry["profession"], []).append(entry)

    groups: list[dict[str, Any]] = []
    for profession, label in PROFESSION_CN.items():
        items = buckets.pop(profession, None)
        if not items:
            continue
        items.sort(key=lambda item: (-item["stars"], item["name"]))
        groups.append(
            {
                "profession": profession,
                "profession_cn": label,
                "operators": items,
            }
        )
    return groups


def find_operator(
    chars: list[dict[str, Any]], char_info: dict[str, Any], query: str
) -> dict[str, Any] | None:
    """Find an owned operator by name.

    Matching prefers an exact name, then an exact match ignoring spaces and
    case, and finally a substring match. Exact matches win so that querying
    ``阿米娅`` does not resolve to ``阿米娅·炎熔``.

    Args:
        chars: The ``chars`` array from the player info payload.
        char_info: The ``charInfoMap`` section.
        query: Operator name supplied by the user.

    Returns:
        The matching operator record, or ``None`` when nothing matches.
    """
    text = str(query or "").strip()
    if not text:
        return None
    char_info = char_info or {}
    candidates = [
        _operator_entry(char, char_info)
        for char in chars or []
        if str(char.get("charId") or "") in char_info
    ]
    if not candidates:
        return None

    for operator in candidates:
        if operator["name"] == text:
            return operator
    compact = text.replace(" ", "")
    for operator in candidates:
        if operator["name"].replace(" ", "") == compact:
            return operator
    lowered = text.lower()
    for operator in candidates:
        if operator["name"].lower() == lowered:
            return operator
    for operator in candidates:
        if lowered in operator["name"].lower():
            return operator
    return None


def build_roster_context(
    groups: list[dict[str, Any]], char_info: dict[str, Any]
) -> dict[str, Any]:
    """Build the roster card context.

    Args:
        groups: Output of :func:`group_operators`.
        char_info: The ``charInfoMap`` section, used for the owned total.

    Returns:
        Template context for ``operator_list.html``.
    """
    return {
        "groups": groups,
        "owned": sum(len(group["operators"]) for group in groups),
        "total": len(char_info or {}),
    }


def build_operator_context(
    operator: dict[str, Any], equipment_info: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the single operator detail card context.

    Args:
        operator: Record produced by :func:`find_operator`.
        equipment_info: The ``equipmentInfoMap`` section, used to resolve module
            names. Entries missing from it fall back to the raw id.

    Returns:
        Template context for ``operator.html``.
    """
    equipment_info = equipment_info or {}
    char_id = str(operator.get("char_id") or "")
    skills = []
    for skill in operator.get("skills") or []:
        skill_id = str(skill.get("id") or "")
        skills.append(
            {
                "id": skill_id,
                "icon": skill_icon(skill_id) if skill_id else "",
                "specialize": int(skill.get("specializeLevel") or 0),
                "is_default": skill_id == str(operator.get("default_skill_id") or ""),
            }
        )
    equips = []
    for equip in operator.get("equip") or []:
        equip_id = str(equip.get("id") or "")
        meta = equipment_info.get(equip_id) or {}
        equips.append(
            {
                "id": equip_id,
                "name": str(meta.get("name") or equip_id),
                "level": int(equip.get("level") or 0),
            }
        )
    return {
        "name": operator.get("name") or char_id,
        "profession_cn": operator.get("profession_cn") or UNKNOWN_PROFESSION_CN,
        "stars": int(operator.get("stars") or 0),
        "level": int(operator.get("level") or 0),
        "elite": int(operator.get("elite") or 0),
        "potential": int(operator.get("potential") or 0),
        "favor": int(operator.get("favor") or 0),
        "favor_percent": min(100, int(operator.get("favor") or 0) // 2),
        "avatar": operator.get("avatar") or (char_avatar(char_id) if char_id else ""),
        "portrait": char_portrait(char_id, 2) if char_id else "",
        "skills": skills,
        "equips": equips,
    }
