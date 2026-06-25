"""Deploy SecurityReviewAgent to Vertex AI Agent Engine as an A2A service.

Usage:
    uv run --group deploy python -m agent_mesh.specialists.security_review_deploy

Required env vars:
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION
    GOOGLE_CLOUD_STAGING_BUCKET  (gs://...)
    GH_TOKEN  — fine-grained PAT with scopes: contents:read, pull_requests:write

Optional env vars:
    SECURITY_REVIEW_ENGINE_ID  — resource name from a prior deploy; triggers update instead of create

Prints card_url to stdout — the deploy workflow captures this as a job output.
On first deploy, also prints the SECURITY_REVIEW_ENGINE_ID to add to GitHub secrets.
"""

import os
import sys

import cloudpickle  # type: ignore  # verify pickling before deploy
import vertexai  # type: ignore  # google-cloud-aiplatform[reasoningengine,adk]
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, TransportProtocol
from vertexai._genai import types  # type: ignore

from agent_mesh.specialists.security_review import (
    SECURITY_REVIEW_AGENT,
    SECURITY_REVIEW_CAPABILITIES,
)

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ["GOOGLE_CLOUD_STAGING_BUCKET"]
GH_TOKEN = os.environ["GH_TOKEN"]
ENGINE_ID = os.environ.get("SECURITY_REVIEW_ENGINE_ID")


def _card() -> AgentCard:
    return AgentCard(
        name="SecurityReviewAgent",
        description=SECURITY_REVIEW_AGENT.description,
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
            for cap in SECURITY_REVIEW_CAPABILITIES
        ],
    )


def _security_review_runner():
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.auth.credential_service.in_memory_credential_service import (
        InMemoryCredentialService,
    )
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return Runner(
        app_name=SECURITY_REVIEW_AGENT.name or "security_review_agent",
        agent=SECURITY_REVIEW_AGENT,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService(),
        credential_service=InMemoryCredentialService(),
    )


def _security_review_executor():
    from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor

    return A2aAgentExecutor(runner=_security_review_runner)


def main() -> None:
    # ponytail: cloudpickle smoke test — Agent Engine pickles the agent before shipping.
    # Fail fast here rather than after a multi-minute upload.
    try:
        cloudpickle.dumps(SECURITY_REVIEW_AGENT)
    except Exception as e:
        print(f"ERROR: SECURITY_REVIEW_AGENT is not picklable: {e}", file=sys.stderr)
        sys.exit(1)

    from vertexai.preview.reasoning_engines import A2aAgent  # type: ignore

    vertexai.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)
    client = vertexai.Client(project=PROJECT, location=REGION)
    app = A2aAgent(
        agent_card=_card(),
        agent_executor_builder=_security_review_executor,
    )
    config = {
        "display_name": "security-review-agent",
        "requirements": ["google-adk[a2a]>=1.25.0", "google-genai"],
        "extra_packages": ["installation_scripts/install_gh.sh"],
        "build_options": {"installation_scripts": ["installation_scripts/install_gh.sh"]},
        "env_vars": {"GH_TOKEN": GH_TOKEN},
        "staging_bucket": BUCKET,
        "identity_type": types.IdentityType.AGENT_IDENTITY,
    }

    if ENGINE_ID:
        remote = client.agent_engines.update(name=ENGINE_ID, agent=app, config=config)
        resource_name = remote.api_resource.name
        print(f"Updated: {resource_name}")
    else:
        remote = client.agent_engines.create(agent=app, config=config)
        resource_name = remote.api_resource.name
        print(f"Created: {resource_name}")
        print(f"→ Add to GitHub secrets: SECURITY_REVIEW_ENGINE_ID={resource_name}")

    card_url = (
        f"https://{REGION}-aiplatform.googleapis.com"
        f"/v1beta1/{resource_name}/a2a/v1/card"
    )
    print(f"card_url: {card_url}")


if __name__ == "__main__":
    main()
