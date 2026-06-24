import pytest
from unittest.mock import MagicMock
from agent_mesh.router_agent import build_router_agent, ROUTER_INSTRUCTION
from agent_mesh.tools import list_all_agents
from agent_mesh import catalog


@pytest.fixture(autouse=True)
def reset_catalog():
    yield
    catalog._locals = []
    catalog._cache = []
    catalog._refreshed_at = 0.0
    catalog._lock = None


def test_router_agent_name_and_output_key():
    agent = build_router_agent()
    assert agent.name == "RouterAgent"
    assert agent.output_key == "task_decomposition"


def test_router_instruction_does_not_fabricate_capabilities():
    assert "fabricate" in ROUTER_INSTRUCTION


def test_router_instruction_calls_list_all_agents():
    assert "list_all_agents" in ROUTER_INSTRUCTION


@pytest.mark.asyncio
async def test_list_all_agents_returns_seeded_catalog():
    a = MagicMock()
    a.name = "WebAgent"
    a.description = "Does web search"
    catalog.seed([(a, ["web_search"])])
    result = await list_all_agents()
    assert len(result) == 1
    assert result[0]["name"] == "WebAgent"
    assert result[0]["capabilities"] == ["web_search"]
    assert {"name", "description", "capabilities"} <= result[0].keys()
