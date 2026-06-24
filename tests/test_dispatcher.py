import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from google.adk.agents import LlmAgent
from agent_mesh.dispatcher import ParallelDispatcher, _build_capability_map
from agent_mesh.models import SpecialistResult
from agent_mesh.tools import TimeoutAgentTool
from agent_mesh import catalog
from agent_mesh.catalog import RemoteSpec

# Valid AE card URL — passes SSRF validator (host *.aiplatform.googleapis.com, reasoningEngines path)
_REMOTE_URL = (
    "https://us-central1-aiplatform.googleapis.com"
    "/v1beta1/projects/test/locations/us-central1/reasoningEngines/123/a2a/v1/card"
)


@pytest.fixture(autouse=True)
def reset_catalog():
    """Reset catalog module globals between tests — dispatcher reads it at call time."""
    yield
    catalog._locals = []
    catalog._cache = []
    catalog._refreshed_at = 0.0
    catalog._lock = None


def make_agent(name: str) -> LlmAgent:
    return LlmAgent(name=name, model="gemini-2.0-flash", description=f"Test {name}")


def make_tool(agent_name: str, return_value=None, raises=None) -> TimeoutAgentTool:
    tool = TimeoutAgentTool(agent=make_agent(agent_name))
    if raises:
        tool.run_async = AsyncMock(side_effect=raises)  # type: ignore
    else:
        tool.run_async = AsyncMock(  # type: ignore
            return_value=return_value
            if return_value is not None
            else f"output from {agent_name}"
        )
    return tool


def make_state(subtasks: list[dict]) -> dict:
    return {
        "task_decomposition": json.dumps(
            {
                "original_task": "test task",
                "subtasks": subtasks,
            }
        )
    }


def make_ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.session.state = state
    return ctx


async def collect(dispatcher: ParallelDispatcher, ctx: MagicMock) -> list:
    events = []
    with patch("agent_mesh.dispatcher.ToolContext", return_value=MagicMock()):
        async for event in dispatcher._run_async_impl(ctx):
            events.append(event)
    return events


@pytest.fixture
def dispatcher() -> ParallelDispatcher:
    return ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": make_tool("AgentA")},
    )


@pytest.mark.asyncio
async def test_successful_dispatch_writes_result_to_state(dispatcher):
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_a",
                    "agent_name": "AgentA",
                    "instruction": "do cap_a",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    # arch F5: result key uses capability string, not agent name
    assert "result_cap_a" in ctx.session.state
    result = SpecialistResult.model_validate_json(ctx.session.state["result_cap_a"])
    assert result.success is True
    assert result.agent_name == "AgentA"


@pytest.mark.asyncio
async def test_unavailable_agent_name_captured_in_state(dispatcher):
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_missing",
                    "agent_name": "UNAVAILABLE",
                    "instruction": "do missing",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    unavailable = json.loads(ctx.session.state["unavailable_capabilities"])
    assert "cap_missing" in unavailable


@pytest.mark.asyncio
async def test_missing_tool_treated_as_unavailable():
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": make_tool("AgentA")},
    )
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_b",
                    "agent_name": "AgentB",
                    "instruction": "do cap_b",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    unavailable = json.loads(ctx.session.state["unavailable_capabilities"])
    assert "cap_b" in unavailable


@pytest.mark.asyncio
async def test_tool_error_dict_captured_as_failed_result():
    tool = make_tool(
        "AgentA", return_value={"error": "SomeError", "message": "it broke"}
    )
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": tool},
    )
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_a",
                    "agent_name": "AgentA",
                    "instruction": "do cap_a",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    result = SpecialistResult.model_validate_json(ctx.session.state["result_cap_a"])
    assert result.success is False
    assert result.error == "it broke"


@pytest.mark.asyncio
async def test_tool_exception_captured_as_failed_result():
    tool = make_tool("AgentA", raises=RuntimeError("boom"))
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": tool},
    )
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_a",
                    "agent_name": "AgentA",
                    "instruction": "do cap_a",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    result = SpecialistResult.model_validate_json(ctx.session.state["result_cap_a"])
    assert result.success is False
    assert result.error and "boom" in result.error


@pytest.mark.asyncio
async def test_malformed_task_decomposition_yields_error_event():
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": make_tool("AgentA")},
    )
    ctx = make_ctx({"task_decomposition": "not valid json {{"})
    events = []
    async for event in dispatcher._run_async_impl(ctx):
        events.append(event)

    assert len(events) == 1
    content = events[0].content
    assert (
        content and content.parts and "Failed to parse" in (content.parts[0].text or "")
    )


@pytest.mark.asyncio
async def test_multiple_specialists_all_dispatched():
    tool_a = make_tool("AgentA")
    tool_b = make_tool("AgentB")
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": tool_a, "cap_b": tool_b},
    )
    ctx = make_ctx(
        make_state(
            [
                {
                    "capability": "cap_a",
                    "agent_name": "AgentA",
                    "instruction": "do cap_a",
                },
                {
                    "capability": "cap_b",
                    "agent_name": "AgentB",
                    "instruction": "do cap_b",
                },
            ]
        )
    )
    await collect(dispatcher, ctx)

    assert "result_cap_a" in ctx.session.state
    assert "result_cap_b" in ctx.session.state
    assert json.loads(ctx.session.state["unavailable_capabilities"]) == []


# ---- Phase 2: remote dispatch ----

@pytest.mark.asyncio
async def test_remote_spec_discovered_at_call_time():
    """Remote spec seeded into catalog AFTER construction is picked up at dispatch time."""
    dispatcher = ParallelDispatcher(
        name="TestDispatcher", description="Test",
        specialist_tools={},  # no locals
    )
    # Seed remote after dispatcher is already constructed
    catalog.seed([], remotes=[
        RemoteSpec(name="RemoteAgent", capabilities=["cap_remote"], a2a_url=_REMOTE_URL)
    ])

    remote_tool = make_tool("RemoteAgent", return_value="remote output")

    with patch.object(dispatcher, "_get_remote_tools", return_value={"cap_remote": remote_tool}):
        ctx = make_ctx(make_state([
            {"capability": "cap_remote", "agent_name": "RemoteAgent", "instruction": "do remote"},
        ]))
        await collect(dispatcher, ctx)

    assert "result_cap_remote" in ctx.session.state
    result = SpecialistResult.model_validate_json(ctx.session.state["result_cap_remote"])
    assert result.success is True
    assert "remote output" in result.output


@pytest.mark.asyncio
async def test_local_wins_over_remote_same_capability():
    """Local agent displaces remote for identical capability (security M2 — local-wins)."""
    local_tool = make_tool("LocalAgent", return_value="local output")
    remote_tool = make_tool("RemoteAgent", return_value="remote output")
    dispatcher = ParallelDispatcher(
        name="TestDispatcher", description="Test",
        specialist_tools={"cap_x": local_tool},
    )

    with patch.object(dispatcher, "_get_remote_tools", return_value={"cap_x": remote_tool}):
        ctx = make_ctx(make_state([
            {"capability": "cap_x", "agent_name": "LocalAgent", "instruction": "do x"},
        ]))
        await collect(dispatcher, ctx)

    result = SpecialistResult.model_validate_json(ctx.session.state["result_cap_x"])
    assert result.output == "local output"  # local won


@pytest.mark.asyncio
async def test_remote_tool_cache_reuses_instances():
    """Same (name, url) remote spec → single RemoteA2aAgent constructed across calls."""
    dispatcher = ParallelDispatcher(
        name="TestDispatcher", description="Test",
        specialist_tools={},
    )
    specs = [RemoteSpec(name="RemoteAgent", capabilities=["cap_r"], a2a_url=_REMOTE_URL)]

    with patch("google.adk.agents.remote_a2a_agent.RemoteA2aAgent") as MockAgent:
        mock_inst = MagicMock()
        mock_inst.name = "RemoteAgent"
        MockAgent.return_value = mock_inst

        dispatcher._get_remote_tools(specs)
        dispatcher._get_remote_tools(specs)

        assert MockAgent.call_count == 1  # only constructed once (cache hit on second call)


def test_build_capability_map_local_wins():
    local = MagicMock()
    remote = MagicMock()
    result = _build_capability_map(
        local_tools={"cap_x": local},
        remote_tools={"cap_x": remote, "cap_y": remote},
    )
    assert result["cap_x"] is local   # local displaced remote
    assert result["cap_y"] is remote   # remote unopposed


def test_ssrf_validator_rejects_non_vertex_url():
    """RemoteSpec rejects a2a_url with non-Vertex host."""
    import pytest
    with pytest.raises(Exception, match="aiplatform.googleapis.com"):
        RemoteSpec(
            name="bad", capabilities=["x"],
            a2a_url="https://attacker.example.com/reasoningEngines/123/a2a"
        )


def test_ssrf_validator_rejects_missing_reasoning_engine_path():
    """RemoteSpec rejects a2a_url with correct host but wrong path shape."""
    import pytest
    with pytest.raises(Exception, match="reasoningEngines"):
        RemoteSpec(
            name="bad", capabilities=["x"],
            a2a_url="https://us-central1-aiplatform.googleapis.com/v1/some/other/path"
        )
