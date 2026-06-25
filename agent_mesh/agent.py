import os
from google.adk.agents import SequentialAgent

from agent_mesh import catalog
from agent_mesh.catalog import RemoteSpec
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    WEB_SEARCH_AGENT,
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_AGENT,
    SUMMARIZER_CAPABILITIES,
)
from agent_mesh.specialists.security_review import SECURITY_REVIEW_CAPABILITIES


def build_pipeline() -> SequentialAgent:
    timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    catalog.build_catalog()

    remotes = []
    if card_url := os.environ.get("AGENT_MESH_SECURITY_REVIEW_CARD_URL"):
        remotes.append(RemoteSpec(
            name="SecurityReviewAgent",
            capabilities=SECURITY_REVIEW_CAPABILITIES,
            a2a_url=card_url,
        ))

    catalog.seed(
        [(WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES), (SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES)],
        remotes=remotes or None,
    )

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
