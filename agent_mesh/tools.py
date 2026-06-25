import asyncio
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext
from google.adk.agents import BaseAgent


async def list_all_agents() -> list[dict]:
    """
    Returns all registered agents with their capabilities.
    Used by RouterAgent as an ADK FunctionTool for task decomposition.
    """
    from agent_mesh.catalog import list_agents
    agents = await list_agents()
    return [
        {"name": a.name, "description": a.description, "capabilities": a.capabilities}
        for a in agents
    ]


class TimeoutAgentTool(AgentTool):
    """AgentTool with per-agent timeout. Returns error dict on timeout — never raises."""

    def __init__(self, agent: BaseAgent, timeout: float = 30.0):
        super().__init__(agent=agent)
        self.timeout = timeout

    async def run_async(self, *, args: dict[str, object], tool_context: ToolContext) -> object:
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
            return {"error": type(e).__name__, "agent": self.agent.name, "message": str(e)}
