"""
Integration tests — require GEMINI_API_KEY to run.
Skipped automatically when the key is absent.
"""
import os
import uuid
import pytest
import pytest_asyncio
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner, RunConfig
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types

from agent_mesh.registry import CapabilityRegistry
from agent_mesh.tools import set_registry, TimeoutAgentTool
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    register_all_specialists,
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_CAPABILITIES,
    CODE_REVIEW_CAPABILITIES,
)
from agent_mesh.models import MeshResponse


def make_fresh_specialists():
    """Create fresh LlmAgent instances — ADK agents cannot be re-parented across tests."""
    web_search = LlmAgent(
        name="WebSearchAgent",
        model="gemini-2.5-flash",
        description="Performs live web searches and returns summarized results with source URLs.",
        instruction="Search the web for the given query. Return a concise summary with source URLs.",
        tools=[google_search],
    )
    summarizer = LlmAgent(
        name="SummarizerAgent",
        model="gemini-2.5-flash",
        description="Summarizes long-form text into concise, structured bullet points.",
        instruction="Summarize the provided text. Be concise. Preserve key facts and source attributions.",
    )
    code_review = LlmAgent(
        name="CodeReviewAgent",
        model="gemini-2.5-flash",
        description="Reviews code samples for bugs, style issues, and improvement opportunities.",
        instruction=(
            "Review the provided code. Identify: bugs, security issues, style violations, "
            "and improvement opportunities. Be specific and actionable."
        ),
    )
    return [
        (web_search, WEB_SEARCH_CAPABILITIES),
        (summarizer, SUMMARIZER_CAPABILITIES),
        (code_review, CODE_REVIEW_CAPABILITIES),
    ]

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set — skipping live integration tests",
)


async def run_task(runner: Runner, session_service: InMemorySessionService, task: str) -> MeshResponse:
    user_id = "test_user"
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name="agent-mesh", user_id=user_id, session_id=session_id
    )
    content = types.Content(role="user", parts=[types.Part(text=task)])
    # Consume all events — ADK contract: stopping early leaves agents mid-run
    async for _ in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
        run_config=RunConfig(max_llm_calls=20),
    ):
        pass
    # Read from session state: SynthesizerAgent writes output_key="mesh_response"
    session = await session_service.get_session(
        app_name="agent-mesh", user_id=user_id, session_id=session_id
    )
    if session:
        raw = session.state.get("mesh_response")
        if raw:
            if isinstance(raw, dict):
                return MeshResponse.model_validate(raw)
            raw = str(raw).strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else "{}"
            return MeshResponse.model_validate_json(raw)
    return MeshResponse(answer="no response", sources=[], partial=True, unavailable_capabilities=[])


@pytest_asyncio.fixture
async def integration_registry(tmp_path):
    r = CapabilityRegistry(db_path=str(tmp_path / "integration.db"))
    await r.initialize()
    await register_all_specialists(r)
    set_registry(r)
    yield r
    set_registry(None)


@pytest_asyncio.fixture
async def mesh_runner(integration_registry):
    session_service = InMemorySessionService()
    specialist_tools: dict[str, TimeoutAgentTool] = {}
    for agent, caps in make_fresh_specialists():
        tool = TimeoutAgentTool(agent=agent, timeout=30.0)
        for cap in caps:
            specialist_tools[cap] = tool

    pipeline = SequentialAgent(
        name="AgentMesh",
        description="Routes tasks to specialist agents and synthesizes results.",
        sub_agents=[
            build_router_agent(),
            ParallelDispatcher(
                name="ParallelDispatcher",
                description="Fans out to healthy specialists in parallel.",
                specialist_tools=specialist_tools,
            ),
            build_synthesizer_agent(),
        ],
    )
    runner = Runner(
        agent=pipeline,
        app_name="agent-mesh",
        session_service=session_service,
    )
    return runner, session_service


@pytest.mark.asyncio
async def test_full_roundtrip_all_specialists_healthy(mesh_runner):
    """All 3 specialists healthy → valid MeshResponse with a non-empty answer."""
    runner, session_service = mesh_runner
    response = await run_task(runner, session_service, "Summarize what Python is used for.")
    assert isinstance(response, MeshResponse)
    assert response.answer


@pytest.mark.asyncio
async def test_partial_response_when_specialist_offline(mesh_runner, integration_registry):
    """Mark CodeReviewAgent offline → MeshResponse.partial=True, unavailable=['code_review']."""
    runner, session_service = mesh_runner
    for _ in range(5):
        await integration_registry.update_liveness("CodeReviewAgent", success=False)
    response = await run_task(
        runner, session_service,
        "Find Python performance tips and review this code: x = [i for i in range(10)]",
    )
    assert response.partial is True
    assert "code_review" in response.unavailable_capabilities


@pytest.mark.asyncio
async def test_platform_does_not_crash_when_all_offline(mesh_runner, integration_registry):
    """All specialists offline → graceful partial response, no exception."""
    runner, session_service = mesh_runner
    for name in ["WebSearchAgent", "SummarizerAgent", "CodeReviewAgent"]:
        for _ in range(5):
            await integration_registry.update_liveness(name, success=False)
    response = await run_task(runner, session_service, "any task")
    assert response.partial is True
    assert response.answer
