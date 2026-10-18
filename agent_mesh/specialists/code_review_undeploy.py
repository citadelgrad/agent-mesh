"""Remove the deployed CodeReviewAgent from Vertex AI Agent Engine.

Usage:
    AGENT_ENGINE_ID=... uv run --group deploy python -m agent_mesh.specialists.code_review_undeploy

Required env vars:
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION
    AGENT_ENGINE_ID
"""

import os

import vertexai  # type: ignore  # google-cloud-aiplatform[reasoningengine,adk]
from vertexai import agent_engines  # type: ignore


def main() -> None:
    vertexai.init(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"],
    )
    agent_engines.get(os.environ["AGENT_ENGINE_ID"]).delete()


if __name__ == "__main__":
    main()
