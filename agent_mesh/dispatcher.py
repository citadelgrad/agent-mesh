import asyncio
import time
import json
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import model_validator
from typing import AsyncGenerator
from agent_mesh.models import TaskDecomposition, SpecialistResult, Subtask
from agent_mesh.tools import TimeoutAgentTool


class ParallelDispatcher(BaseAgent):
    """
    Reads task_decomposition from session.state, fans out to specialist agents
    concurrently via asyncio.gather, writes SpecialistResult records to session.state.
    Never raises — all failures are captured as SpecialistResult(success=False).
    """
    specialist_tools: dict[str, TimeoutAgentTool]  # capability -> TimeoutAgentTool

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="before")
    @classmethod
    def register_sub_agents(cls, data: dict) -> dict:
        tools: dict[str, TimeoutAgentTool] = data.get("specialist_tools", {})
        # Deduplicate: multiple capabilities may map to same agent
        seen_agents = {}
        for tool in tools.values():
            if tool.agent.name not in seen_agents:
                seen_agents[tool.agent.name] = tool.agent
        data["sub_agents"] = list(seen_agents.values())
        return data

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        raw = ctx.session.state.get("task_decomposition", "{}")
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else "{}"
        try:
            decomposition = TaskDecomposition.model_validate_json(
                raw if isinstance(raw, str) else json.dumps(raw)
            )
        except Exception as e:
            yield Event(
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text=f"Failed to parse task_decomposition: {e}")])
            )
            return

        dispatch_tasks = []
        unavailable = []

        for subtask in decomposition.subtasks:
            if subtask.agent_name == "UNAVAILABLE":
                unavailable.append(subtask.capability)
                continue
            tool = self.specialist_tools.get(subtask.capability)
            if tool is None:
                unavailable.append(subtask.capability)
                continue
            dispatch_tasks.append(self._invoke_specialist(tool, subtask, ctx))

        results: list[SpecialistResult] = list(await asyncio.gather(*dispatch_tasks))

        for result in results:
            key = f"result_{result.agent_name.lower().replace(' ', '_')}"
            ctx.session.state[key] = result.model_dump_json()

        ctx.session.state["unavailable_capabilities"] = json.dumps(unavailable)

        summary = f"Dispatched {len(results)} subtasks. Unavailable: {unavailable or 'none'}"
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=summary)])
        )

    async def _invoke_specialist(
        self,
        tool: TimeoutAgentTool,
        subtask: Subtask,
        ctx: InvocationContext,
    ) -> SpecialistResult:
        start = time.monotonic()
        try:
            tool_ctx = ToolContext(invocation_context=ctx)
            result_raw = await tool.run_async(
                args={"request": subtask.instruction},
                tool_context=tool_ctx,
            )
            if isinstance(result_raw, dict) and "error" in result_raw:
                return SpecialistResult(
                    agent_name=subtask.agent_name,
                    capability=subtask.capability,
                    output="",
                    success=False,
                    error=result_raw.get("message"),
                    duration_seconds=time.monotonic() - start,
                )
            return SpecialistResult(
                agent_name=subtask.agent_name,
                capability=subtask.capability,
                output=str(result_raw),
                success=True,
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            return SpecialistResult(
                agent_name=subtask.agent_name,
                capability=subtask.capability,
                output="",
                success=False,
                error=str(e),
                duration_seconds=time.monotonic() - start,
            )
