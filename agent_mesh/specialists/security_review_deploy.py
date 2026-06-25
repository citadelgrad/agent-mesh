"""Deploy SecurityReviewAgent to Vertex AI Agent Engine as an A2A service.

Usage:
    uv run --group deploy python -m agent_mesh.specialists.security_review_deploy

Required env vars:
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION
    GOOGLE_CLOUD_STAGING_BUCKET  (gs://...)
    GH_TOKEN  — fine-grained PAT with scopes: contents:read, pull_requests:write

Prints the card URL to stdout — paste into .envrc as AGENT_MESH_SECURITY_REVIEW_CARD_URL.

Note: When wiring this agent into TimeoutAgentTool, raise its timeout to 300s.
      The default is too short for multi-step OWASP scans that call gh CLI repeatedly.
"""

import os
import sys

import cloudpickle  # type: ignore  # verify pickling before deploy
import vertexai  # type: ignore  # google-cloud-aiplatform[reasoningengine,adk]
from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from vertexai import agent_engines  # type: ignore
from vertexai.preview.reasoning_engines import A2aAgent  # type: ignore

from agent_mesh.specialists.security_review import (
    SECURITY_REVIEW_AGENT,
    SECURITY_REVIEW_CAPABILITIES,
)

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ["GOOGLE_CLOUD_LOCATION"]
BUCKET = os.environ["GOOGLE_CLOUD_STAGING_BUCKET"]
GH_TOKEN = os.environ["GH_TOKEN"]


def _card() -> AgentCard:
    return AgentCard(
        name="SecurityReviewAgent",
        description=SECURITY_REVIEW_AGENT.description,
        url="",  # Agent Engine fills this in after deploy
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(id=cap, name=cap.replace("_", " ").title(), description=cap)
            for cap in SECURITY_REVIEW_CAPABILITIES
        ],
    )


def main() -> None:
    # ponytail: cloudpickle smoke test — Agent Engine pickles the agent before shipping.
    # Fail fast here rather than after a multi-minute upload.
    try:
        cloudpickle.dumps(SECURITY_REVIEW_AGENT)
    except Exception as e:
        print(f"ERROR: SECURITY_REVIEW_AGENT is not picklable: {e}", file=sys.stderr)
        sys.exit(1)

    vertexai.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)

    app = A2aAgent(agent=SECURITY_REVIEW_AGENT, agent_card=_card())
    engine = agent_engines.create(
        app,
        display_name="security-review-agent",
        requirements=["google-adk[a2a]>=1.25.0", "google-genai"],
        extra_packages=["installation_scripts/install_gh.sh"],
        build_options={"installation_scripts": ["installation_scripts/install_gh.sh"]},
        env_vars={"GH_TOKEN": GH_TOKEN},
        identity_type="AGENT_IDENTITY",
    )

    card_url = (
        f"https://{REGION}-aiplatform.googleapis.com"
        f"/v1beta1/{engine.resource_name}/a2a/v1/card"
    )
    print(f"resource_name: {engine.resource_name}")
    print(f"card_url:      {card_url}")
    print()
    print(f'Add to .envrc: export AGENT_MESH_SECURITY_REVIEW_CARD_URL="{card_url}"')


if __name__ == "__main__":
    main()
