import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from google.adk.agents import LlmAgent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.models import SpecialistResult
from agent_mesh.tools import TimeoutAgentTool


def make_agent(name: str) -> LlmAgent:
    return LlmAgent(name=name, model="gemini-2.0-flash", description=f"Test {name}")


def make_tool(agent_name: str, return_value=None, raises=None) -> TimeoutAgentTool:
    tool = TimeoutAgentTool(agent=make_agent(agent_name))
    if raises:
        tool.run_async = AsyncMock(side_effect=raises)
    else:
        tool.run_async = AsyncMock(
            return_value=return_value if return_value is not None else f"output from {agent_name}"
        )
    return tool


def make_state(subtasks: list[dict]) -> dict:
    return {"task_decomposition": json.dumps({
        "original_task": "test task",
        "subtasks": subtasks,
    })}


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
    ctx = make_ctx(make_state([
        {"capability": "cap_a", "agent_name": "AgentA", "instruction": "do cap_a"},
    ]))
    await collect(dispatcher, ctx)

    assert "result_agenta" in ctx.session.state
    result = SpecialistResult.model_validate_json(ctx.session.state["result_agenta"])
    assert result.success is True
    assert result.agent_name == "AgentA"


@pytest.mark.asyncio
async def test_unavailable_agent_name_captured_in_state(dispatcher):
    ctx = make_ctx(make_state([
        {"capability": "cap_missing", "agent_name": "UNAVAILABLE", "instruction": "do missing"},
    ]))
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
    ctx = make_ctx(make_state([
        {"capability": "cap_b", "agent_name": "AgentB", "instruction": "do cap_b"},
    ]))
    await collect(dispatcher, ctx)

    unavailable = json.loads(ctx.session.state["unavailable_capabilities"])
    assert "cap_b" in unavailable


@pytest.mark.asyncio
async def test_tool_error_dict_captured_as_failed_result():
    tool = make_tool("AgentA", return_value={"error": "SomeError", "message": "it broke"})
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": tool},
    )
    ctx = make_ctx(make_state([
        {"capability": "cap_a", "agent_name": "AgentA", "instruction": "do cap_a"},
    ]))
    await collect(dispatcher, ctx)

    result = SpecialistResult.model_validate_json(ctx.session.state["result_agenta"])
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
    ctx = make_ctx(make_state([
        {"capability": "cap_a", "agent_name": "AgentA", "instruction": "do cap_a"},
    ]))
    await collect(dispatcher, ctx)

    result = SpecialistResult.model_validate_json(ctx.session.state["result_agenta"])
    assert result.success is False
    assert "boom" in result.error


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
    assert "Failed to parse" in events[0].content.parts[0].text


@pytest.mark.asyncio
async def test_multiple_specialists_all_dispatched():
    tool_a = make_tool("AgentA")
    tool_b = make_tool("AgentB")
    dispatcher = ParallelDispatcher(
        name="TestDispatcher",
        description="Test",
        specialist_tools={"cap_a": tool_a, "cap_b": tool_b},
    )
    ctx = make_ctx(make_state([
        {"capability": "cap_a", "agent_name": "AgentA", "instruction": "do cap_a"},
        {"capability": "cap_b", "agent_name": "AgentB", "instruction": "do cap_b"},
    ]))
    await collect(dispatcher, ctx)

    assert "result_agenta" in ctx.session.state
    assert "result_agentb" in ctx.session.state
    assert json.loads(ctx.session.state["unavailable_capabilities"]) == []
