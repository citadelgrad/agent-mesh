import pytest
from agent_mesh.registry import CapabilityRegistry


@pytest.mark.asyncio
async def test_register_and_list_all(registry):
    await registry.register("AgentA", "Does A", ["cap_a"])
    agents = await registry.list_all()
    assert any(a.name == "AgentA" for a in agents)


@pytest.mark.asyncio
async def test_deregister_removes_agent(registry):
    await registry.register("AgentA", "Does A", ["cap_a"])
    await registry.deregister("AgentA")
    agents = await registry.list_all()
    assert not any(a.name == "AgentA" for a in agents)


@pytest.mark.asyncio
async def test_lookup_by_capability(registry):
    await registry.register("AgentA", "Does A", ["cap_a", "cap_b"])
    assert (await registry.lookup("cap_b")).name == "AgentA"
    assert await registry.lookup("cap_missing") is None


@pytest.mark.asyncio
async def test_persistence_survives_reinit(tmp_path):
    r1 = CapabilityRegistry(db_path=str(tmp_path / "test.db"))
    await r1.initialize()
    await r1.register("AgentA", "Does A", ["cap_a"])
    r2 = CapabilityRegistry(db_path=str(tmp_path / "test.db"))
    await r2.initialize()
    assert any(a.name == "AgentA" for a in await r2.list_all())
