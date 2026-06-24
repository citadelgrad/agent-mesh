import os
from google.adk.agents import SequentialAgent

from agent_mesh import catalog
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    WEB_SEARCH_AGENT,
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_AGENT,
    SUMMARIZER_CAPABILITIES,
)


def build_pipeline() -> SequentialAgent:
    timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    catalog.build_catalog()
    catalog.seed([
        (WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES),
        (SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES),
    ])

    return SequentialAgent(
        name="AgentMesh",
        description="Routes tasks to specialist agents and synthesizes results.",
        sub_agents=[
            build_router_agent(),
            ParallelDispatcher(
                name="ParallelDispatcher",
                description="Fans out to specialists in parallel.",
                specialist_tools=catalog.build_tools(timeout),
            ),
            build_synthesizer_agent(),
        ],
    )
