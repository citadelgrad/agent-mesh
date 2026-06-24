import asyncio
import pytest
from unittest.mock import MagicMock, patch
from agent_mesh import catalog as cat
from agent_mesh.catalog import AgentRegistryCatalog, RemoteSpec, StaticCatalog

# Valid Vertex AI A2A URL shape required by RemoteSpec validator
FAKE_URL = (
    "https://us-central1-aiplatform.googleapis.com"
    "/v1beta1/projects/p/locations/us-central1/reasoningEngines/123/a2a/v1/card"
)


def _agent(name: str):
    m = MagicMock()
    m.name = name
    m.description = f"{name} description"
    return m


@pytest.fixture(autouse=True)
def reset_catalog():
    yield
    cat._locals = []
    cat._cache = []
    cat._refreshed_at = 0.0
    cat._lock = None
    cat._active_catalog = None


def test_seed_populates_cache():
    cat.seed([(_agent("A"), ["cap_a", "cap_b"])])
    assert len(cat._cache) == 1
    assert cat._cache[0].capabilities == ["cap_a", "cap_b"]


@pytest.mark.asyncio
async def test_list_agents_returns_seeded():
    cat.seed([(_agent("A"), ["cap_a"])])
    agents = await cat.list_agents()
    assert len(agents) == 1
    assert agents[0].name == "A"


def test_build_tools_maps_all_capabilities():
    cat.seed([(_agent("A"), ["cap_a", "cap_b"])])
    with patch("agent_mesh.tools.TimeoutAgentTool") as MockTool:
        MockTool.return_value = MagicMock()
        tools = cat.build_tools(timeout=10.0)
    assert set(tools) == {"cap_a", "cap_b"}
    assert tools["cap_a"] is tools["cap_b"]  # same tool instance


def test_build_tools_deduplicates_by_agent_name():
    a = _agent("A")
    # Same agent name in two seed entries → one TimeoutAgentTool
    cat.seed([(a, ["cap_a"]), (a, ["cap_b"])])
    created = []
    with patch("agent_mesh.tools.TimeoutAgentTool", side_effect=lambda **kw: created.append(MagicMock()) or created[-1]):
        cat.build_tools(timeout=5.0)
    assert len(created) == 1


@pytest.mark.asyncio
async def test_list_agents_concurrent():
    cat.seed([(_agent("A"), ["cap_a"])])
    results = await asyncio.gather(*[cat.list_agents() for _ in range(20)])
    assert all(len(r) == 1 for r in results)


# --- AgentRegistryCatalog tests ---

@pytest.mark.asyncio
async def test_agent_registry_catalog_fetches_and_caches(monkeypatch):
    arc = AgentRegistryCatalog("proj", "us-central1", ttl=3600.0)
    arc._refreshed_at = -9999.0  # force expired

    call_count = 0

    def mock_fetch():
        nonlocal call_count
        call_count += 1
        return [RemoteSpec(name="A", capabilities=["cap_a"], a2a_url=FAKE_URL)]

    monkeypatch.setattr(arc, "_fetch_from_registry", mock_fetch)

    result1 = await arc.list_agents()
    result2 = await arc.list_agents()  # within TTL — should not re-fetch

    assert call_count == 1
    assert len(result1) == 1
    assert len(result2) == 1


@pytest.mark.asyncio
async def test_agent_registry_catalog_stale_on_error(monkeypatch):
    arc = AgentRegistryCatalog("proj", "us-central1", ttl=3600.0)
    stale = RemoteSpec(name="A", capabilities=["cap_a"], a2a_url=FAKE_URL)
    arc._cache = [stale]
    arc._refreshed_at = -9999.0  # expired

    def raise_error():
        raise RuntimeError("registry down")

    monkeypatch.setattr(arc, "_fetch_from_registry", raise_error)

    before = arc._refreshed_at
    result = await arc.list_agents()

    assert result == [stale]                          # stale cache returned
    assert arc._refreshed_at == pytest.approx(before + 30, abs=1)  # expiry extended


@pytest.mark.asyncio
async def test_agent_registry_catalog_double_checked_locking(monkeypatch):
    arc = AgentRegistryCatalog("proj", "us-central1", ttl=3600.0)
    arc._refreshed_at = -9999.0  # expired

    call_count = 0

    def mock_fetch():
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(arc, "_fetch_from_registry", mock_fetch)

    await asyncio.gather(*[arc.list_agents() for _ in range(10)])
    assert call_count == 1


def test_build_catalog_returns_static_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_MESH_USE_REGISTRY", raising=False)
    result = cat.build_catalog()
    assert isinstance(result, StaticCatalog)


def test_build_catalog_returns_registry_when_flag_set(monkeypatch):
    monkeypatch.setenv("AGENT_MESH_USE_REGISTRY", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east1")
    result = cat.build_catalog()
    assert isinstance(result, AgentRegistryCatalog)
    assert result._project == "my-project"
    assert result._location == "us-east1"


def test_agent_registry_catalog_picklable():
    import cloudpickle
    arc = AgentRegistryCatalog("proj", "us-central1")
    cloudpickle.dumps(arc)  # must not raise — lazy-init lock is not yet created
