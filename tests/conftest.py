import pytest
import pytest_asyncio
from agent_mesh.registry import CapabilityRegistry


@pytest_asyncio.fixture
async def registry(tmp_path):
    r = CapabilityRegistry(db_path=str(tmp_path / "test.db"))
    await r.initialize()
    return r


@pytest.fixture
def always_healthy():
    async def fn():
        return True
    return fn


@pytest.fixture
def always_failing():
    async def fn():
        return False
    return fn
