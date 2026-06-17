import pytest
from agent_mesh.registry import CapabilityRegistry


@pytest.mark.asyncio
async def test_healthy_agent_appears_in_list_healthy(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    agents = await registry.list_healthy()
    assert any(a.name == "AgentA" for a in agents)


@pytest.mark.asyncio
async def test_degraded_after_two_failures(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    await registry.update_liveness("AgentA", success=False)
    await registry.update_liveness("AgentA", success=False)
    agents = await registry.list_healthy()
    agent = next(a for a in agents if a.name == "AgentA")
    assert agent.status == "degraded"


@pytest.mark.asyncio
async def test_degraded_still_appears_in_list_healthy(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    for _ in range(2):
        await registry.update_liveness("AgentA", success=False)
    agents = await registry.list_healthy()
    assert any(a.name == "AgentA" for a in agents), "degraded agents must appear in list_healthy"


@pytest.mark.asyncio
async def test_offline_after_five_failures(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    for _ in range(5):
        await registry.update_liveness("AgentA", success=False)
    agents = await registry.list_healthy()
    assert not any(a.name == "AgentA" for a in agents), "offline agent must not appear in list_healthy"


@pytest.mark.asyncio
async def test_recovery_offline_to_degraded(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    for _ in range(5):
        await registry.update_liveness("AgentA", success=False)
    await registry.update_liveness("AgentA", success=True)
    agents = await registry.list_healthy()
    assert any(a.name == "AgentA" for a in agents), "1 success from offline should move to degraded (visible in list_healthy)"


@pytest.mark.asyncio
async def test_recovery_degraded_to_healthy(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    for _ in range(2):
        await registry.update_liveness("AgentA", success=False)
    await registry.update_liveness("AgentA", success=True)
    await registry.update_liveness("AgentA", success=True)
    agents = await registry.list_healthy()
    agent = next(a for a in agents if a.name == "AgentA")
    assert agent.status == "healthy"


@pytest.mark.asyncio
async def test_persistence_survives_reinit(tmp_path, always_healthy):
    r1 = CapabilityRegistry(db_path=str(tmp_path / "test.db"))
    await r1.initialize()
    await r1.register("AgentA", "Does A", ["cap_a"], always_healthy)
    r2 = CapabilityRegistry(db_path=str(tmp_path / "test.db"))
    await r2.initialize()
    agents = await r2.list_healthy()
    assert any(a.name == "AgentA" for a in agents), "agents must persist across registry instances"


@pytest.mark.asyncio
async def test_lookup_returns_healthy_agent(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a", "cap_b"], always_healthy)
    result = await registry.lookup("cap_b")
    assert result is not None
    assert result.name == "AgentA"


@pytest.mark.asyncio
async def test_lookup_returns_none_for_missing_capability(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    result = await registry.lookup("cap_missing")
    assert result is None


@pytest.mark.asyncio
async def test_deregister_removes_agent(registry, always_healthy):
    await registry.register("AgentA", "Does A", ["cap_a"], always_healthy)
    await registry.deregister("AgentA")
    agents = await registry.list_healthy()
    assert not any(a.name == "AgentA" for a in agents)
