import asyncio
import logging
import time
import json
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import PrivateAttr, model_validator
from typing import AsyncGenerator
from agent_mesh.models import TaskDecomposition, SpecialistResult, Subtask
from agent_mesh.tools import TimeoutAgentTool

logger = logging.getLogger(__name__)


def _event_invocation_id(ctx: InvocationContext) -> str:
    invocation_id = getattr(ctx, "invocation_id", "")
    return invocation_id if isinstance(invocation_id, str) else "test-invocation"


def _build_capability_map(
    local_tools: dict[str, TimeoutAgentTool],
    remote_tools: dict[str, TimeoutAgentTool],
) -> dict[str, TimeoutAgentTool]:
    """Merge local and remote tools. Local wins on capability collision.
    ponytail: local-wins closes the silent capability-hijack vector (security M2).
    Remote-remote ties are already broken alphabetically in _get_remote_tools."""
    merged = dict(remote_tools)
    for cap, tool in local_tools.items():
        if cap in merged:
            logger.info("local agent displaces remote for capability %r", cap)
        merged[cap] = tool  # local overwrites remote unconditionally
    return merged


class ParallelDispatcher(BaseAgent):
    """
    Reads task_decomposition from session.state, fans out to specialist agents
    concurrently via asyncio.gather, writes SpecialistResult records to session.state.
    Never raises — all failures are captured as SpecialistResult(success=False).
    """
    specialist_tools: dict[str, TimeoutAgentTool]  # local agents, built at startup

    model_config = {"arbitrary_types_allowed": True}

    # ponytail: PrivateAttr — not in Pydantic schema; keyed on (name, a2a_url) to avoid
    # reconstructing RemoteA2aAgent (and its httpx client) per request (arch F4).
    _remote_tool_cache: dict = PrivateAttr(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def register_sub_agents(cls, data: dict) -> dict:
        # ponytail: RemoteA2aAgent bypasses sub_agents graph (it makes HTTP calls via its
        # own A2A client, not ADK sub-agent dispatch). Only register local agents here.
        tools: dict[str, TimeoutAgentTool] = data.get("specialist_tools", {})
        seen_agents = {}
        for tool in tools.values():
            if tool.agent.name not in seen_agents:
                seen_agents[tool.agent.name] = tool.agent
        data["sub_agents"] = list(seen_agents.values())
        return data

    def _get_remote_tools(self, specs) -> dict[str, TimeoutAgentTool]:
        """Build TimeoutAgentTool for remote specs using instance cache keyed on (name, url).
        Sorted by name for deterministic alphabetical-first tiebreak on same capability."""
        from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

        result: dict[str, TimeoutAgentTool] = {}
        for spec in sorted(specs, key=lambda s: s.name):
            if spec.a2a_url is None:
                continue
            cache_key = (spec.name, spec.a2a_url)
            if cache_key not in self._remote_tool_cache:
                remote = RemoteA2aAgent(name=spec.name, agent_card=spec.a2a_url)
                self._remote_tool_cache[cache_key] = TimeoutAgentTool(agent=remote, timeout=60.0)
            tool = self._remote_tool_cache[cache_key]
            for cap in spec.capabilities:
                if cap not in result:  # alphabetical-first wins for remote-remote collision
                    result[cap] = tool
        return result

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
                invocation_id=_event_invocation_id(ctx),
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text=f"Failed to parse task_decomposition: {e}")])
            )
            return

        # Build merged tool dict: local (construction-time) + remote (catalog at call-time)
        from agent_mesh.catalog import list_agents
        specs = await list_agents()
        remote_tools = self._get_remote_tools(specs)
        all_tools = _build_capability_map(self.specialist_tools, remote_tools)

        dispatch_tasks = []
        unavailable = []

        for subtask in decomposition.subtasks:
            if subtask.agent_name == "UNAVAILABLE":
                unavailable.append(subtask.capability)
                continue
            tool = all_tools.get(subtask.capability)
            if tool is None:
                unavailable.append(subtask.capability)
                continue
            dispatch_tasks.append(self._invoke_specialist(tool, subtask, ctx))

        results: list[SpecialistResult] = list(await asyncio.gather(*dispatch_tasks))

        for result in results:
            # ponytail: key on capability string, not agent name — router echoes capability
            # verbatim; agent names can drift across versions (arch F5)
            key = f"result_{result.capability.lower().replace(' ', '_')}"
            ctx.session.state[key] = result.model_dump_json()

        ctx.session.state["unavailable_capabilities"] = json.dumps(unavailable)

        summary = f"Dispatched {len(results)} subtasks. Unavailable: {unavailable or 'none'}"
        yield Event(
            invocation_id=_event_invocation_id(ctx),
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
                error_type = result_raw.get("error", "")
                error_kind = "timeout" if error_type == "TimeoutError" else "http_error"
                return SpecialistResult(
                    agent_name=subtask.agent_name,
                    capability=subtask.capability,
                    output="",
                    success=False,
                    error=result_raw.get("message"),
                    error_kind=error_kind,
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
                error_kind="unknown",
                duration_seconds=time.monotonic() - start,
            )
