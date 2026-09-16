"""URL builders for official Arknights game assets.

Assets are served by the PRTS Wiki mirror of the game resource bundle at
``torappu.prts.wiki``, which was verified to serve operator avatars, elite
portraits and skill icons. Only paths that were actually confirmed are exposed
here; anything else is rendered as text instead of guessing a URL.
"""

from __future__ import annotations

ASSET_BASE = "https://torappu.prts.wiki/assets"


def char_avatar(char_id: str) -> str:
    """Return the square avatar URL for an operator.

    Args:
        char_id: Internal operator id, e.g. ``char_002_amiya``.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/char_avatar/{char_id}.png"


def char_portrait(char_id: str, phase: int = 2) -> str:
    """Return the half-body portrait URL for an operator.

    Args:
        char_id: Internal operator id.
        phase: Promotion phase; ``1`` is elite 1, ``2`` is elite 2.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/char_portrait/{char_id}_{phase}.png"


def skill_icon(skill_id: str) -> str:
    """Return the icon URL for a skill.

    Args:
        skill_id: Internal skill id, e.g. ``skchr_amiya_3``.

    Returns:
        Absolute image URL.
    """
    return f"{ASSET_BASE}/skill_icon/skill_icon_{skill_id}.png"
