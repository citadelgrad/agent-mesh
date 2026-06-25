import json
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from typing import AsyncGenerator
from agent_mesh.models import MeshResponse, SpecialistResult

_loads = json.loads


def _event_invocation_id(ctx: InvocationContext) -> str:
    invocation_id = getattr(ctx, "invocation_id", "")
    return invocation_id if isinstance(invocation_id, str) else "test-invocation"


class BaseSynthesizer(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = (ctx.session and ctx.session.state) or {}
        results = []
        for key, val in state.items():
            if key.startswith("result_"):
                try:
                    results.append(SpecialistResult.model_validate_json(val))
                except Exception:  # noqa: S112  # nosec B112
                    continue

        unavailable_raw = state.get("unavailable_capabilities", "[]")
        try:
            if isinstance(unavailable_raw, str):
                unavailable = _loads(unavailable_raw)
            else:
                unavailable = list(unavailable_raw)
        except Exception:
            unavailable = []

        successful = [r for r in results if r.success]
        partial = bool(
            not results or any(not r.success for r in results) or unavailable
        )

        if successful:
            # ponytail: H1 — delimiters prevent a remote agent's output from spoofing
            # synthesizer formatting (e.g. injecting fake [capability] headers).
            answer = "\n\n".join(
                f'<specialist_output capability="{r.capability}">\n{r.output}\n</specialist_output>'
                for r in successful
            )
        else:
            answer = (
                "All specialists are currently unavailable."
                if unavailable
                else "No specialists were dispatched."
            )

        response = MeshResponse(
            answer=answer,
            sources=[r.agent_name for r in successful],
            partial=partial,
            unavailable_capabilities=unavailable,
        )
        ctx.session.state["mesh_response"] = response.model_dump()

        yield Event(
            invocation_id=_event_invocation_id(ctx),
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=response.model_dump_json())]
            ),
        )


def build_synthesizer_agent() -> BaseSynthesizer:
    return BaseSynthesizer(
        name="SynthesizerAgent",
        description="Assembles parallel specialist results into a final structured response.",
    )
