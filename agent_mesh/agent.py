import asyncio
import os
from google.adk.agents import SequentialAgent

from agent_mesh.registry import CapabilityRegistry
from agent_mesh.tools import set_registry, TimeoutAgentTool
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    register_all_specialists,
    WEB_SEARCH_AGENT,
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_AGENT,
    SUMMARIZER_CAPABILITIES,
    CODE_REVIEW_AGENT,
    CODE_REVIEW_CAPABILITIES,
)


def build_pipeline() -> SequentialAgent:
    # Agent Engine containers are ephemeral; specialists re-seed on each cold start.
    # Use a temp-file SQLite DB instead of ":memory:" because aiosqlite opens a
    # new connection per registry method, and each ":memory:" connection gets an
    # empty database.
    async def _init():
        registry = CapabilityRegistry(
            db_path=os.getenv("AGENT_MESH_DB_PATH", "/tmp/agent-mesh/mesh.db")
        )
        await registry.initialize()
        await register_all_specialists(registry)
        set_registry(registry)

    asyncio.run(_init())

    timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    specialist_tools: dict[str, TimeoutAgentTool] = {}
    for agent, caps in [
        (WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES),
        (SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES),
        (CODE_REVIEW_AGENT, CODE_REVIEW_CAPABILITIES),
    ]:
        tool = TimeoutAgentTool(agent=agent, timeout=timeout)
        for cap in caps:
            specialist_tools[cap] = tool

    return SequentialAgent(
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
