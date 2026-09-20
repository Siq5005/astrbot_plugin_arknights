"""Install a stand-in ``astrbot.api.logger`` when the framework is absent.

The plugin market requires plugin loggers to come from ``astrbot.api``, so the
``core`` modules import it. AstrBot ships as a uv project rather than an
installed package, which means the unit tests and the standalone scripts would
otherwise need a full framework checkout just to import the plugin.

Both callers must run this before importing anything from ``core``. It is one
module rather than two copies because the logger import already changed once and
the preview script silently broke when it did.
"""

import sys
import types


def ensure_framework_logger() -> None:
    """Make ``from astrbot.api import logger`` work without AstrBot installed."""
    try:
        import astrbot.api  # noqa: F401
    except ImportError:
        pass
    else:
        return

    class _NullLogger:
        """Swallows plugin log output; logging is not what these runs cover."""

        def _ignore(self, *args: object, **kwargs: object) -> None:
            """Accept any logging call and discard it."""

        debug = info = warning = error = exception = critical = _ignore

    api = types.ModuleType("astrbot.api")
    api.logger = _NullLogger()
    framework = types.ModuleType("astrbot")
    framework.api = api
    sys.modules.setdefault("astrbot", framework)
    sys.modules.setdefault("astrbot.api", api)
