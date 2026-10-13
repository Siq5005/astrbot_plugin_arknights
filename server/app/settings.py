"""Runtime configuration, read from ``ARKSOURCE_*`` environment variables.

Keeping every deployment-specific value here means the same code runs in a local
venv and on the public host without edits.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable.

    Args:
        name: Variable name.
        default: Value used when unset or unparsable.

    Returns:
        The parsed integer, or ``default``.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Aggregator settings."""

    api_key: str
    credential_file: Path
    state_file: Path
    host: str
    port: int
    poll_interval_seconds: int
    window_hours: int
    stale_minutes: int

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment.

        Returns:
            A populated :class:`Settings`.
        """
        return cls(
            api_key=os.environ.get("ARKSOURCE_API_KEY", "").strip(),
            credential_file=Path(
                os.environ.get(
                    "ARKSOURCE_CREDENTIAL_FILE", "/opt/arksource/credentials.json"
                )
            ),
            state_file=Path(
                os.environ.get("ARKSOURCE_STATE_FILE", "/opt/arksource/state.json")
            ),
            host=os.environ.get("ARKSOURCE_HOST", "127.0.0.1").strip(),
            port=_env_int("ARKSOURCE_PORT", 8788),
            # A zero interval would busy-loop against Skland with no delay.
            poll_interval_seconds=max(1, _env_int("ARKSOURCE_POLL_INTERVAL", 600)),
            window_hours=_env_int("ARKSOURCE_WINDOW_HOURS", 72),
            stale_minutes=_env_int("ARKSOURCE_STALE_MINUTES", 60),
        )
