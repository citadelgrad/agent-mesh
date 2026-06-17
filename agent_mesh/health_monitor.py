import asyncio
import logging
import aiosqlite
from agent_mesh.registry import CapabilityRegistry, _row_to_record

logger = logging.getLogger(__name__)


async def _list_all(registry: CapabilityRegistry):
    """Returns ALL agents including offline (for recovery polling)."""
    async with aiosqlite.connect(registry._db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
    return [_row_to_record(r) for r in rows]


async def health_monitor_loop(
    registry: CapabilityRegistry,
    interval_seconds: float = 30.0,
) -> None:
    """
    Runs indefinitely as an asyncio task. Cancel the task to stop.
    Polls ALL registered agents (including offline) so they can recover.
    Updates registry liveness after each poll.
    health_check_fn timeout is hard-coded to 5s per agent.
    """
    while True:
        all_agents = await _list_all(registry)
        for record in all_agents:
            check_fn = registry.get_health_check(record.name)
            if check_fn is None:
                continue
            try:
                alive = await asyncio.wait_for(check_fn(), timeout=5.0)
            except asyncio.TimeoutError:
                alive = False
            except Exception:
                logger.exception("health_check raised for %s", record.name)
                alive = False
            await registry.update_liveness(record.name, alive)
            logger.debug("health_check %s -> %s", record.name, "ok" if alive else "fail")
        await asyncio.sleep(interval_seconds)
