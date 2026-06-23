import pytest
from agent_mesh.router_agent import build_router_agent, ROUTER_INSTRUCTION
from agent_mesh.tools import list_healthy, set_registry


def test_router_agent_name_and_output_key():
    agent = build_router_agent()
    assert agent.name == "RouterAgent"
    assert agent.output_key == "task_decomposition"


def test_router_instruction_marks_missing_capability_unavailable():
    assert "UNAVAILABLE" in ROUTER_INSTRUCTION


def test_router_instruction_calls_list_all_agents():
    assert "list_all_agents" in ROUTER_INSTRUCTION


@pytest.mark.asyncio
async def test_list_healthy_bootstraps_when_no_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_DB_PATH", str(tmp_path / "mesh.db"))
    set_registry(None)
    result = await list_healthy()
    assert {agent["name"] for agent in result} == {
        "CodeReviewAgent",
        "SummarizerAgent",
        "WebSearchAgent",
    }


@pytest.mark.asyncio
async def test_list_healthy_returns_healthy_agents(registry, always_healthy):
    await registry.register(
        "WebAgent", "Does web search", ["web_search"], always_healthy
    )
    set_registry(registry)
    try:
        result = await list_healthy()
        assert any(r["name"] == "WebAgent" for r in result)
        assert all({"name", "capabilities", "status"} <= r.keys() for r in result)
    finally:
        set_registry(None)


@pytest.mark.asyncio
async def test_list_healthy_excludes_offline_agents(registry):
    async def failing():
        return False

    await registry.register("OfflineAgent", "Goes offline", ["cap_x"], failing)
    for _ in range(5):
        await registry.update_liveness("OfflineAgent", success=False)
    set_registry(registry)
    try:
        result = await list_healthy()
        assert not any(r["name"] == "OfflineAgent" for r in result)
    finally:
        set_registry(None)
