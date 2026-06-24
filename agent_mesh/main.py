import asyncio
import os
from google.adk.agents import SequentialAgent
from google.adk.runners import Runner, RunConfig
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from agent_mesh.observability import setup_telemetry
from agent_mesh import catalog
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    WEB_SEARCH_AGENT,
    WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_AGENT,
    SUMMARIZER_CAPABILITIES,
)
from agent_mesh.models import MeshResponse


async def main() -> None:
    setup_telemetry()

    db_path = os.getenv("AGENT_MESH_DB_PATH", "./data/mesh.db")
    session_service = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{db_path}")

    timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    catalog.build_catalog()
    catalog.seed([
        (WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES),
        (SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES),
    ])

    pipeline = SequentialAgent(
        name="AgentMesh",
        description="Routes tasks to specialist agents and synthesizes results.",
        sub_agents=[
            build_router_agent(),
            ParallelDispatcher(
                name="ParallelDispatcher",
                description="Fans out to specialists in parallel.",
                specialist_tools=catalog.build_tools(timeout),
            ),
            build_synthesizer_agent(),
        ],
    )

    runner = Runner(
        agent=pipeline,
        app_name="agent-mesh",
        session_service=session_service,
    )

    user_id = "local_user"
    session_id = "cli_session"
    if not await session_service.get_session(
        app_name="agent-mesh", user_id=user_id, session_id=session_id
    ):
        await session_service.create_session(
            app_name="agent-mesh", user_id=user_id, session_id=session_id
        )

    loop = asyncio.get_running_loop()
    print("Agent Mesh ready. Enter a task (Ctrl+C to quit):\n")
    try:
        while True:
            task = await loop.run_in_executor(None, lambda: input("> ").strip())
            if not task:
                continue
            content = types.Content(role="user", parts=[types.Part(text=task)])
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
                run_config=RunConfig(max_llm_calls=20),
            ):
                if event.is_final_response():
                    raw = (
                        event.content.parts[0].text or ""
                        if event.content and event.content.parts
                        else ""
                    )
                    try:
                        response = MeshResponse.model_validate_json(raw)
                        print(f"\n{response.answer}")
                        if response.partial:
                            print(f"\n[Note: unavailable: {', '.join(response.unavailable_capabilities)}]")
                    except Exception:
                        print(f"\n{raw}")
                    print()
    except KeyboardInterrupt:
        pass
    print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
