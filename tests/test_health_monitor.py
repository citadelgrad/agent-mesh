import asyncio
import pytest
from agent_mesh.health_monitor import health_monitor_loop


@pytest.mark.asyncio
async def test_health_monitor_marks_agent_offline(registry):
    async def failing_check():
        return False

    await registry.register("AgentB", "Does B", ["cap_b"], failing_check)

    # Drive liveness directly — avoids sleeping in tests
    for _ in range(5):
        check_fn = registry.get_health_check("AgentB")
        alive = await check_fn()
        await registry.update_liveness("AgentB", alive)

    agents = await registry.list_healthy()
    assert not any(a.name == "AgentB" for a in agents), "agent should be offline after 5 failures"


@pytest.mark.asyncio
async def test_health_monitor_loop_cancels_cleanly(registry):
    async def healthy():
        return True

    await registry.register("AgentC", "Does C", ["cap_c"], healthy)

    task = asyncio.create_task(health_monitor_loop(registry, interval_seconds=0.05))
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # ponytail: CancelledError is the happy path here
