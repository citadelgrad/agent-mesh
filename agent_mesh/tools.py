import asyncio
import os
from typing import Any
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext
from google.adk.agents import BaseAgent

# ponytail: module-level singleton, injected before runner starts
_registry = None


def set_registry(registry) -> None:
    global _registry
    _registry = registry


async def _ensure_registry():
    """Lazily initialize specialist registry after Agent Engine unpickles the app."""
    global _registry
    if _registry is None:
        from agent_mesh.registry import CapabilityRegistry

        _registry = CapabilityRegistry(
            db_path=os.getenv("AGENT_MESH_DB_PATH", "/tmp/agent-mesh/mesh.db")
        )
        await _registry.initialize()

    agents = await _registry.list_all()
    if not agents:
        from agent_mesh.specialists import register_all_specialists

        await register_all_specialists(_registry)
        agents = await _registry.list_all()
    return _registry, agents


async def list_all_agents() -> list[dict]:
    """
    Returns ALL registered agents (healthy, degraded, AND offline) with their status and capabilities.
    Use this in the router so offline capabilities can be marked UNAVAILABLE in task decomposition.
    """
    _, agents = await _ensure_registry()
    return [
        {
            "name": a.name,
            "description": a.description,
            "capabilities": a.capabilities,
            "status": a.status,
        }
        for a in agents
    ]


async def list_healthy() -> list[dict]:
    """
    Returns all currently-healthy or degraded agents with their capabilities.
    Use this to discover what the platform can do before decomposing a task.
    ADK wraps this as a FunctionTool when passed in tools=[list_healthy].
    """
    registry, _ = await _ensure_registry()
    agents = await registry.list_healthy()
    return [
        {
            "name": a.name,
            "description": a.description,
            "capabilities": a.capabilities,
            "status": a.status,
        }
        for a in agents
    ]


class TimeoutAgentTool(AgentTool):
    """
    AgentTool with per-agent timeout. Returns a structured error dict on timeout
    so the dispatcher can record the failure without raising an exception.
    """

    def __init__(self, agent: BaseAgent, timeout: float = 30.0):
        super().__init__(agent=agent)
        self.timeout = timeout

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Any:
        try:
            return await asyncio.wait_for(
                super().run_async(args=args, tool_context=tool_context),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return {
                "error": "TimeoutError",
                "agent": self.agent.name,
                "message": f"Agent '{self.agent.name}' timed out after {self.timeout}s",
            }
        except Exception as e:
            return {
                "error": type(e).__name__,
                "agent": self.agent.name,
                "message": str(e),
            }
