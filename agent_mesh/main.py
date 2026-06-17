import asyncio
import os
from google.adk.agents import SequentialAgent
from google.adk.runners import Runner, RunConfig
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from agent_mesh.observability import setup_telemetry
from agent_mesh.registry import CapabilityRegistry
from agent_mesh.health_monitor import health_monitor_loop
from agent_mesh.tools import set_registry, TimeoutAgentTool
from agent_mesh.router_agent import build_router_agent
from agent_mesh.dispatcher import ParallelDispatcher
from agent_mesh.synthesizer import build_synthesizer_agent
from agent_mesh.specialists import (
    register_all_specialists,
    WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES,
    SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES,
    CODE_REVIEW_AGENT, CODE_REVIEW_CAPABILITIES,
)
from agent_mesh.models import MeshResponse


async def main() -> None:
    # 1. Telemetry first (must precede any agent creation)
    setup_telemetry()

    # 2. Registry + session persistence (both SQLite)
    db_path = os.getenv("AGENT_MESH_DB_PATH", "./data/mesh.db")
    registry = CapabilityRegistry(db_path=db_path)
    await registry.initialize()

    # ADK constraint: DatabaseSessionService takes SQLAlchemy URL, not bare path
    # Use sqlite:// (relative path needs 3 slashes for absolute, 4 for relative)
    session_service = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{db_path}")

    # 3. Register specialists and wire registry to the list_healthy tool
    await register_all_specialists(registry)
    set_registry(registry)

    # 4. Background health monitor (plain asyncio task, not LoopAgent — bug #1100)
    monitor_task = asyncio.create_task(
        health_monitor_loop(
            registry,
            interval_seconds=float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "30")),
        )
    )

    # 5. Build specialist tool wrappers for the dispatcher
    timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))
    specialist_tools: dict[str, TimeoutAgentTool] = {}
    for agent, caps in [
        (WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES),
        (SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES),
        (CODE_REVIEW_AGENT, CODE_REVIEW_CAPABILITIES),
    ]:
        tool = TimeoutAgentTool(agent=agent, timeout=timeout)
        for cap in caps:
            specialist_tools[cap] = tool

    # 6. Build the sequential pipeline
    pipeline = SequentialAgent(
        name="AgentMesh",
        description="Routes tasks to specialist agents and synthesizes results.",
        sub_agents=[
            build_router_agent(),
            ParallelDispatcher(
                name="ParallelDispatcher",
                description="Fans out to healthy specialists in parallel.",
                specialist_tools=specialist_tools,
            ),
            build_synthesizer_agent(),
        ],
    )

    # 7. Runner
    runner = Runner(
        agent=pipeline,
        app_name="agent-mesh",
        session_service=session_service,
    )

    # 8. Session setup
    user_id = "local_user"
    session_id = "cli_session"
    if not await session_service.get_session(app_name="agent-mesh", user_id=user_id, session_id=session_id):
        await session_service.create_session(
            app_name="agent-mesh", user_id=user_id, session_id=session_id
        )

    # 9. CLI loop
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
                    raw = event.content.parts[0].text if event.content and event.content.parts else ""
                    try:
                        response = MeshResponse.model_validate_json(raw)
                        print(f"\n{response.answer}")
                        if response.partial:
                            print(f"\n[Note: unavailable capabilities: {', '.join(response.unavailable_capabilities)}]")
                    except Exception:
                        print(f"\n{raw}")
                    print()
    except KeyboardInterrupt:
        pass
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
