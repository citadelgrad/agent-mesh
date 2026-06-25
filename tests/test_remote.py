import cloudpickle
import pytest
from agent_mesh.remote import AeRemoteAgent, _GoogleCloudAuth

_CARD_URL = (
    "https://us-central1-aiplatform.googleapis.com"
    "/v1beta1/projects/p/locations/us-central1/reasoningEngines/123/a2a/v1/card"
)


def test_ae_remote_agent_pickles_before_first_request():
    """AeRemoteAgent must survive cloudpickle at construction time (ADK #3004)."""
    agent = AeRemoteAgent(name="TestRemote", agent_card=_CARD_URL)
    data = cloudpickle.dumps(agent)
    restored = cloudpickle.loads(data)
    assert restored.name == "TestRemote"


@pytest.mark.asyncio
async def test_ensure_httpx_client_injects_auth():
    """First call to _ensure_httpx_client creates a client with GoogleCloudAuth."""
    import httpx

    agent = AeRemoteAgent(name="TestRemote", agent_card=_CARD_URL)
    assert agent._httpx_client is None  # not held at init

    client = await agent._ensure_httpx_client()
    assert isinstance(client, httpx.AsyncClient)
    assert isinstance(client.auth, _GoogleCloudAuth)


@pytest.mark.asyncio
async def test_ensure_httpx_client_is_cached():
    """Second call returns the same client instance (no reconstruction)."""
    agent = AeRemoteAgent(name="TestRemote", agent_card=_CARD_URL)
    c1 = await agent._ensure_httpx_client()
    c2 = await agent._ensure_httpx_client()
    assert c1 is c2


def test_google_cloud_auth_flow_sets_bearer():
    """GoogleCloudAuth.auth_flow attaches Authorization: Bearer header."""
    from unittest.mock import MagicMock

    creds = MagicMock()
    creds.valid = True
    creds.token = "tok"  # nosec B105 — test fixture token

    auth = _GoogleCloudAuth()
    auth._creds = creds  # skip google.auth.default call

    request = MagicMock()
    request.headers = {}
    list(auth.auth_flow(request))  # exhaust the generator

    assert request.headers["Authorization"] == "Bearer tok"


# ---- Synthesizer H1 ----

@pytest.mark.asyncio
async def test_synthesizer_wraps_output_in_specialist_delimiters():
    """BaseSynthesizer wraps each specialist's output in <specialist_output> tags (H1)."""
    import json
    from unittest.mock import MagicMock
    from agent_mesh.synthesizer import build_synthesizer_agent
    from agent_mesh.models import SpecialistResult

    result = SpecialistResult(
        agent_name="CodeReviewAgent",
        capability="code_review",
        output="looks good",
        success=True,
        duration_seconds=0.1,
    )
    ctx = MagicMock()
    ctx.session.state = {
        "result_code_review": result.model_dump_json(),
        "unavailable_capabilities": json.dumps([]),
    }
    ctx.invocation_id = "test"

    synth = build_synthesizer_agent()
    events = [e async for e in synth._run_async_impl(ctx)]
    assert len(events) == 1

    import json as _json
    try:
        payload = _json.loads(events[0].content.parts[0].text)
    except _json.JSONDecodeError as exc:
        raise AssertionError(f"Expected valid JSON response: {exc}") from exc
    answer = payload["answer"]
    assert '<specialist_output capability="code_review">' in answer
    assert "looks good" in answer
    assert "</specialist_output>" in answer
