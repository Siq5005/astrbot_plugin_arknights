"""URL builders for Arknights game assets.

Three verified sources are used, each chosen for what it actually serves:

* ``torappu.prts.wiki/assets`` — the official resource bundle: operator avatars,
  promotion portraits and skill icons.
* ``Aceship/Arknight-Images`` — profession badges, promotion/potential/rarity
  marks, infrastructure icons and skin portraits.
* ``yuanyan3060/ArknightsGameResource`` — skin artwork, item rarity frames and
  base-skill icons.

Every path here was probed before being added; nothing is guessed. Assets that
cannot be resolved fall back to text in the templates rather than to a broken
image. See the README for source attribution.
"""

from __future__ import annotations

from typing import Any

ASSET_BASE = "https://torappu.prts.wiki/assets"
ACESHIP_BASE = "https://cdn.jsdelivr.net/gh/Aceship/Arknight-Images@main"
RESOURCE_BASE = "https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main"

# charInfoMap profession -> Aceship class badge file stem.
PROFESSION_ICON: dict[str, str] = {
    "PIONEER": "class_vanguard",
    "WARRIOR": "class_guard",
    "TANK": "class_defender",
    "SNIPER": "class_sniper",
    "CASTER": "class_caster",
    "MEDIC": "class_medic",
    "SUPPORT": "class_supporter",
    "SPECIAL": "class_specialist",
}

# Facility key -> Aceship infrastructure icon file stem.
FACILITY_ICON: dict[str, str] = {
    "power": "power",
    "manufacture": "manu",
    "trading": "trade",
    "dormitory": "dorm",
    "control": "control",
    "meeting": "meet",
    "hire": "hire",
    "training": "train",
}


def _quote(segment: str) -> str:
    """Percent-encode the characters that appear in game asset file names."""
    return segment.replace("#", "%23")


def char_avatar(char_id: str) -> str:
    """Return the square avatar URL for an operator.

    Args:
        char_id: Internal operator id, e.g. ``char_002_amiya``.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/char_avatar/{_quote(char_id)}.png"


def char_portrait(char_id: str, phase: int = 2) -> str:
    """Return the half-body promotion portrait URL for an operator.

    Args:
        char_id: Internal operator id.
        phase: Promotion phase; ``1`` is elite 1, ``2`` is elite 2.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/char_portrait/{_quote(char_id)}_{phase}.png"


def skill_icon(skill_id: str) -> str:
    """Return the icon URL for a skill.

    Args:
        skill_id: Internal skill id, e.g. ``skchr_amiya_3``.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/skill_icon/skill_icon_{_quote(skill_id)}.png"


def profession_icon(profession: str) -> str:
    """Return the class badge URL for a profession.

    Args:
        profession: ``charInfoMap`` profession value, e.g. ``CASTER``.

    Returns:
        Absolute image URL, or an empty string for an unknown profession.
    """
    stem = PROFESSION_ICON.get(str(profession or "").upper())
    return f"{ACESHIP_BASE}/classes/{stem}.png" if stem else ""


def rarity_icon(stars: int) -> str:
    """Return the rarity mark URL.

    Args:
        stars: Star rating from 1 to 6.

    Returns:
        Absolute image URL, or an empty string when out of range.
    """
    return f"{ACESHIP_BASE}/ui/rank/{stars}.png" if 1 <= stars <= 6 else ""


def elite_icon(phase: int) -> str:
    """Return the promotion (精英化) mark URL.

    Args:
        phase: Promotion phase, ``0`` to ``2``.

    Returns:
        Absolute image URL, or an empty string when out of range.
    """
    return f"{ACESHIP_BASE}/ui/elite/{phase}.png" if 0 <= phase <= 2 else ""


def potential_icon(rank: int) -> str:
    """Return the potential (潜能) mark URL.

    Args:
        rank: Potential rank from 1 to 5.

    Returns:
        Absolute image URL, or an empty string when out of range.
    """
    return f"{ACESHIP_BASE}/ui/potential/{rank}.png" if 1 <= rank <= 5 else ""


def facility_icon(key: str) -> str:
    """Return the infrastructure icon URL for a facility.

    Args:
        key: Facility key used by :func:`core.daily.build_building_context`.

    Returns:
        Absolute image URL, or an empty string for an unknown facility.
    """
    stem = FACILITY_ICON.get(str(key or ""))
    return f"{ACESHIP_BASE}/ui/infrastructure/{stem}.png" if stem else ""


def item_rarity_frame(rarity: int) -> str:
    """Return the item rarity frame URL.

    Args:
        rarity: Item rarity from 1 to 6.

    Returns:
        Absolute image URL, or an empty string when out of range.
    """
    if not 1 <= rarity <= 6:
        return ""
    return f"{RESOURCE_BASE}/item_rarity_img/sprite_item_r{rarity}.png"


def item_icon(icon_id: str) -> str:
    """Return the icon URL for an item.

    Args:
        icon_id: ``itemId`` or ``iconId`` from the game data, e.g. ``3003``.

    Returns:
        Absolute image URL, or an empty string when the id is blank.
    """
    return f"{ACESHIP_BASE}/items/{_quote(icon_id)}.png" if icon_id else ""


def building_skill_icon(skill_id: str) -> str:
    """Return the base-skill icon URL.

    Args:
        skill_id: Base skill id, e.g. ``bskill_ctrl_amiya``.

    Returns:
        Absolute image URL, or an empty string when the id is blank.
    """
    if not skill_id:
        return ""
    return f"{RESOURCE_BASE}/building_skill/{_quote(skill_id)}.png"


def skin_portrait(skin_id: str) -> str:
    """Return the artwork URL for an operator skin.

    Skin ids look like ``char_002_amiya#2`` (a promotion outfit) or
    ``char_002_amiya@winter#1`` (a named outfit). The resource bundle stores
    them as ``char_002_amiya_2b.png`` and ``char_002_amiya_winter#1b.png``
    respectively, so the ``@`` becomes an underscore and a bare promotion index
    swaps its ``#`` for an underscore too.

    Args:
        skin_id: Skin id from the player info payload.

    Returns:
        Absolute image URL, or an empty string when the id is blank.
    """
    skin_id = str(skin_id or "")
    if not skin_id:
        return ""
    if "@" in skin_id:
        stem = skin_id.replace("@", "_", 1)
    else:
        stem = skin_id.replace("#", "_", 1)
    return f"{RESOURCE_BASE}/skin/{_quote(stem)}b.png"


# Assistant artwork modes. ``random`` is the pool the user asked to keep for
# later: it picks between the two promotion portraits plus the worn outfit, all
# of which were probed and are known to resolve.
SECRETARY_MODE_ELITE1 = "elite1"
SECRETARY_MODE_ELITE2 = "elite2"
SECRETARY_MODE_SKIN = "skin"
SECRETARY_MODE_RANDOM = "random"


def secretary_portrait(
    char_id: str,
    skin_id: str = "",
    mode: str = SECRETARY_MODE_ELITE1,
    rng: Any = None,
) -> str:
    """Return the artwork to show for an assistant (助理) operator.

    The default is the elite-1 portrait for every operator, which keeps the
    assistant column visually consistent. Other modes are available through
    configuration:

    * ``elite1`` / ``elite2`` — always that promotion portrait.
    * ``skin`` — the outfit the operator currently wears, falling back to elite 1.
    * ``random`` — pick at random from the pool that actually exists for this
      operator (both promotion portraits plus a named outfit when one is worn).

    Args:
        char_id: Internal operator id.
        skin_id: Skin the operator is currently wearing.
        mode: One of the ``SECRETARY_MODE_*`` values.
        rng: Optional ``random.Random`` used by the random mode, for tests.

    Returns:
        Absolute image URL, or an empty string when no operator was given.
    """
    import random as _random

    char_id = str(char_id or "")
    skin_id = str(skin_id or "")
    if not char_id:
        return ""

    named_skin = bool(skin_id) and not skin_id.startswith(f"{char_id}#")
    if mode == SECRETARY_MODE_ELITE2:
        return char_portrait(char_id, 2)
    if mode == SECRETARY_MODE_SKIN:
        if named_skin:
            return skin_portrait(skin_id)
        return (
            char_portrait(char_id, 2)
            if skin_id.endswith("#2")
            else char_portrait(char_id, 1)
        )
    if mode == SECRETARY_MODE_RANDOM:
        pool = [char_portrait(char_id, 1), char_portrait(char_id, 2)]
        if named_skin:
            pool.append(skin_portrait(skin_id))
        return (rng or _random).choice(pool)
    # elite1 (default), and the fallback for any unknown mode
    return char_portrait(char_id, 1)
