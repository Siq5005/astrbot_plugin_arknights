"""Settings are read from the environment so the same code runs locally and on HK."""

import os
from pathlib import Path

from app.settings import Settings


def test_from_env_applies_defaults(monkeypatch):
    for key in list(os.environ):
        if key.startswith("ARKSOURCE_"):
            monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8788
    assert settings.poll_interval_seconds == 600
    assert settings.window_hours == 72
    assert settings.stale_minutes == 60
    assert settings.api_key == ""


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("ARKSOURCE_API_KEY", "secret-key")
    monkeypatch.setenv("ARKSOURCE_PORT", "9999")
    monkeypatch.setenv("ARKSOURCE_CREDENTIAL_FILE", "/tmp/cred.json")

    settings = Settings.from_env()

    assert settings.api_key == "secret-key"
    assert settings.port == 9999
    assert settings.credential_file == Path("/tmp/cred.json")


def test_from_env_floors_poll_interval_at_one_second(monkeypatch):
    monkeypatch.setenv("ARKSOURCE_POLL_INTERVAL", "0")

    settings = Settings.from_env()

    # A zero interval would busy-loop against Skland with no delay.
    assert settings.poll_interval_seconds == 1
