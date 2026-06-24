"""
Integration tests — require GEMINI_API_KEY to run.
Skipped automatically when the key is absent.
"""

import os
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner, RunConfig
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types

from agent_mesh import catalog
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_CAPABILITIES,
    CODE_REVIEW_CAPABILITIES,
)
from agent_mesh.models import MeshResponse

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse


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


async def run_task(
    runner: Runner, session_service: InMemorySessionService, task: str
) -> MeshResponse:
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
    return MeshResponse(
        answer="no response", sources=[], partial=True, unavailable_capabilities=[]
    )


@pytest_asyncio.fixture
async def mesh_runner():
    catalog.seed(make_fresh_specialists())
    session_service = InMemorySessionService()
    pipeline = SequentialAgent(
        name="AgentMesh",
        description="Routes tasks to specialist agents and synthesizes results.",
        sub_agents=[
            build_router_agent(),
            ParallelDispatcher(
                name="ParallelDispatcher",
                description="Fans out to specialists in parallel.",
                specialist_tools=catalog.build_tools(30.0),
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
    """All 3 specialists available → valid MeshResponse with a non-empty answer."""
    runner, session_service = mesh_runner
    response = await run_task(
        runner, session_service, "Summarize what Python is used for."
    )
    assert isinstance(response, MeshResponse)
    assert response.answer


@pytest.mark.asyncio
async def test_platform_does_not_crash_when_no_subtasks(mesh_runner):
    """Router returns no subtasks → graceful response, no crash."""
    runner, session_service = mesh_runner

    async def _mock_llm(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text='{"original_task":"any task","subtasks":[]}')],
            ),
            turn_complete=True,
        )

    with patch.object(Gemini, "generate_content_async", _mock_llm):
        response = await run_task(runner, session_service, "any task")

    assert response.answer
