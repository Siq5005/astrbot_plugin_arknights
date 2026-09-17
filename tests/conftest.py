"""Shared test fixtures.

The plugin market requires every plugin logger to come from ``astrbot.api``,
including the modules under ``core``. AstrBot ships as a uv project rather than
an installed package, so it is not importable in a bare ``pytest`` run from the
plugin directory; the stub below keeps the unit tests runnable anyway.

The stub only fills the gap when the real framework is missing — the
integration check runs against a real AstrBot and exercises the genuine import.
"""

import sys
import types

import pytest

try:  # pragma: no cover - depends on whether AstrBot is importable
    import astrbot.api  # noqa: F401
except ImportError:  # pragma: no cover

    class _NullLogger:
        """Swallows plugin log output; logging is not what these tests cover."""

        def _ignore(self, *args: object, **kwargs: object) -> None:
            """Accept any logging call and discard it."""

        debug = info = warning = error = exception = critical = _ignore

    _api = types.ModuleType("astrbot.api")
    _api.logger = _NullLogger()
    _framework = types.ModuleType("astrbot")
    _framework.api = _api
    sys.modules.setdefault("astrbot", _framework)
    sys.modules.setdefault("astrbot.api", _api)


@pytest.fixture
def anyio_backend():
    """Force anyio's pytest plugin to run async tests on asyncio only."""
    return "asyncio"
