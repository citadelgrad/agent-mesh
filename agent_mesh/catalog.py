from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class RemoteSpec(BaseModel):
    """Serializable catalog entry. Used by the router for discovery."""
    name: str
    description: str = ""
    capabilities: list[str]
    a2a_url: str | None = None  # None = local in-process; set for remote A2A agents

    @field_validator("a2a_url")
    @classmethod
    def _validate_a2a_url(cls, v: str | None) -> str | None:
        # ponytail: SSRF C2 — targets must be Vertex AI endpoints derived at deploy time,
        # never runtime/user input. One shape assertion replaces the *.run.app allowlist.
        if v is None:
            return v
        parsed = urlparse(v)
        if not re.fullmatch(r"[a-z0-9-]+-aiplatform\.googleapis\.com", parsed.netloc):
            raise ValueError(
                f"a2a_url host must be *.aiplatform.googleapis.com, got {parsed.netloc!r}"
            )
        if not re.search(r"/reasoningEngines/[^/]+/a2a", parsed.path):
            raise ValueError(
                f"a2a_url path must match /reasoningEngines/{{id}}/a2a, got {parsed.path!r}"
            )
        return v


@dataclass
class _LocalSpec:
    name: str
    description: str
    agent: object  # BaseAgent — untyped to avoid ADK import at module level
    capabilities: list[str]


@runtime_checkable
class AgentCatalog(Protocol):
    async def list_agents(self) -> list[RemoteSpec]: ...


class StaticCatalog:
    """Delegates list_agents() to the module-level seed()/_cache. CI/test default."""

    async def list_agents(self) -> list[RemoteSpec]:
        return list(_cache)


class AgentRegistryCatalog:
    """Read-only adapter over GCP Agent Registry REST API with TTL cache."""

    def __init__(self, project: str, location: str, ttl: float = 300.0) -> None:
        self._project = project
        self._location = location
        self._ttl = ttl
        self._cache: list[RemoteSpec] = []
        self._refreshed_at: float = 0.0
        # ponytail: lazy-init — asyncio.Lock is unpicklable at class level (ADK #3004)
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def list_agents(self) -> list[RemoteSpec]:
        if time.monotonic() - self._refreshed_at < self._ttl:
            return list(self._cache)
        async with self._get_lock():
            if time.monotonic() - self._refreshed_at < self._ttl:
                return list(self._cache)
            try:
                self._cache = await asyncio.get_running_loop().run_in_executor(
                    None, self._fetch_from_registry
                )
                self._refreshed_at = time.monotonic()
            except Exception:
                self._refreshed_at += 30  # stale-on-error: serve stale, retry in 30s
        return list(self._cache)

    def _fetch_from_registry(self) -> list[RemoteSpec]:
        from google.auth import default as gauth_default  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415

        creds, _ = gauth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        svc = build("agentregistry", "v1alpha", credentials=creds)
        parent = f"projects/{self._project}/locations/{self._location}"
        resp = svc.projects().locations().agents().list(parent=parent).execute()
        specs = []
        for agent in resp.get("agents", []):
            name = agent.get("displayName", "")
            skills = agent.get("agentSpec", {}).get("skills", [])
            caps = [s["id"] for s in skills if "id" in s]
            interfaces = agent.get("interfaces", [])
            a2a_url = next(
                (i["url"] for i in interfaces if i.get("protocolBinding") == "A2A"), None
            )
            if name and caps and a2a_url:
                specs.append(RemoteSpec(name=name, capabilities=caps, a2a_url=a2a_url))
        return specs


# Module-level state (used by StaticCatalog and the shim functions below)
_locals: list[_LocalSpec] = []
_cache: list[RemoteSpec] = []
_refreshed_at: float = 0.0
TTL: float = 300.0
# ponytail: lazy-init — asyncio.Lock is unpicklable at class level (ADK #3004)
_lock: asyncio.Lock | None = None
_active_catalog: AgentCatalog | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def build_catalog() -> AgentCatalog:
    global _active_catalog
    if os.getenv("AGENT_MESH_USE_REGISTRY", "").lower() in ("1", "true", "yes"):
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        _active_catalog = AgentRegistryCatalog(project=project, location=location)
    else:
        _active_catalog = StaticCatalog()
    return _active_catalog


def seed(
    specialists: list[tuple],
    remotes: list[RemoteSpec] | None = None,
) -> None:
    """Seed catalog from local specialists and optional remote specs.
    Each tuple is (BaseAgent, list[str]). Remote specs have a2a_url set."""
    global _locals, _cache, _refreshed_at
    _locals = [
        _LocalSpec(
            name=agent.name,
            description=getattr(agent, "description", "") or "",
            agent=agent,
            capabilities=list(caps),
        )
        for agent, caps in specialists
    ]
    local_specs = [
        RemoteSpec(name=s.name, description=s.description, capabilities=s.capabilities)
        for s in _locals
    ]
    _cache = local_specs + list(remotes or [])
    _refreshed_at = time.monotonic()


def build_tools(timeout: float) -> dict:
    """Build capability→TimeoutAgentTool from seeded locals. Called once at startup."""
    from agent_mesh.tools import TimeoutAgentTool  # deferred: tools.py imports catalog

    result: dict = {}
    seen: dict = {}
    for spec in _locals:
        if spec.name not in seen:
            seen[spec.name] = TimeoutAgentTool(agent=spec.agent, timeout=timeout)
        tool = seen[spec.name]
        for cap in spec.capabilities:
            result[cap] = tool
    return result


async def list_agents() -> list[RemoteSpec]:
    """Return current catalog snapshot. Delegates to active catalog if set by build_catalog()."""
    if _active_catalog is not None:
        return await _active_catalog.list_agents()
    return list(_cache)
