"""Read and write the long-lived Hypergryph passport token.

The token is what a one-time QR login produces; short-lived Skland credentials
are minted from it on demand and never persisted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_user_token(path: Path) -> str:
    """Read the stored passport token.

    Args:
        path: Credential file written by ``scripts/login.py``.

    Returns:
        The token, or an empty string when absent or unreadable.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("user_token") or "")


def save_user_token(path: Path, token: str) -> None:
    """Persist the passport token with owner-only permissions.

    Args:
        path: Destination file.
        token: Passport token to store.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"user_token": token}, ensure_ascii=False), encoding="utf-8"
    )
    os.chmod(destination, 0o600)
