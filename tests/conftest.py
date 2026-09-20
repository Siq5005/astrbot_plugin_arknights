"""Shared test fixtures.

See ``framework_stub`` for why the logger stub exists.
"""

import pytest
from framework_stub import ensure_framework_logger

ensure_framework_logger()


@pytest.fixture
def anyio_backend():
    """Force anyio's pytest plugin to run async tests on asyncio only."""
    return "asyncio"
