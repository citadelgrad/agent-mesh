"""Deploy CodeReviewAgent to Vertex AI Agent Engine as an A2A service.

Usage:
    uv run --group deploy python -m agent_mesh.specialists.code_review_deploy

Required env vars:
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION
    GOOGLE_CLOUD_STAGING_BUCKET  (gs://...)

Prints the card URL to stdout — paste into .envrc as AGENT_MESH_CODE_REVIEW_CARD_URL.
"""

import os
import sys

import cloudpickle  # type: ignore  # verify pickling before deploy
import vertexai  # type: ignore  # google-cloud-aiplatform[reasoningengine,adk]
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, TransportProtocol
from vertexai import agent_engines  # type: ignore
from vertexai.preview.reasoning_engines import A2aAgent  # type: ignore

from agent_mesh.specialists.code_review import CODE_REVIEW_AGENT, CODE_REVIEW_CAPABILITIES

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ["GOOGLE_CLOUD_LOCATION"]
BUCKET = os.environ["GOOGLE_CLOUD_STAGING_BUCKET"]


def _card() -> AgentCard:
    return AgentCard(
        name="CodeReviewAgent",
        description=CODE_REVIEW_AGENT.description,
        url="",  # Agent Engine fills this in after deploy
        version="1.0.0",
        preferred_transport=TransportProtocol.http_json,
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id=cap,
                name=cap.replace("_", " ").title(),
                description=cap,
                tags=[cap],
            )
            for cap in CODE_REVIEW_CAPABILITIES
        ],
    )


def _code_review_runner():
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.auth.credential_service.in_memory_credential_service import (
        InMemoryCredentialService,
    )
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return Runner(
        app_name=CODE_REVIEW_AGENT.name or "code_review_agent",
        agent=CODE_REVIEW_AGENT,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService(),
        credential_service=InMemoryCredentialService(),
    )


def _code_review_executor():
    from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor

    return A2aAgentExecutor(runner=_code_review_runner)


def main() -> None:
    # ponytail: cloudpickle smoke test — Agent Engine pickles the agent before shipping.
    # Fail fast here rather than after a multi-minute upload.
    try:
        cloudpickle.dumps(CODE_REVIEW_AGENT)
    except Exception as e:
        print(f"ERROR: CODE_REVIEW_AGENT is not picklable: {e}", file=sys.stderr)
        sys.exit(1)

    vertexai.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)

    app = A2aAgent(
        agent_card=_card(),
        agent_executor_builder=_code_review_executor,
    )
    engine = agent_engines.create(
        app,
        display_name="code-review-agent",
        requirements=["google-adk[a2a]>=1.25.0", "google-genai"],
        identity_type="AGENT_IDENTITY",
    )

    card_url = (
        f"https://{REGION}-aiplatform.googleapis.com"
        f"/v1beta1/{engine.resource_name}/a2a/v1/card"
    )
    print(f"resource_name: {engine.resource_name}")
    print(f"card_url:      {card_url}")
    print()
    print(f'Add to .envrc: export AGENT_MESH_CODE_REVIEW_CARD_URL="{card_url}"')


if __name__ == "__main__":
    main()
