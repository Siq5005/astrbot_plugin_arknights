import pytest


@pytest.fixture
def anyio_backend():
    """Force anyio's pytest plugin to run async tests on asyncio only."""
    return "asyncio"
