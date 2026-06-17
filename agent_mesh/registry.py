import aiosqlite
import json
from pathlib import Path
from datetime import datetime, timezone
from agent_mesh.models import AgentRecord
from typing import Callable, Awaitable


class CapabilityRegistry:
    def __init__(self, db_path: str = "./data/mesh.db"):
        self._db_path = db_path
        self._health_checks: dict[str, Callable[[], Awaitable[bool]]] = {}

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'healthy',
                    timeout_seconds REAL NOT NULL DEFAULT 30.0,
                    last_checked_at TEXT,
                    registered_at TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    consecutive_successes INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.commit()

    async def register(self, name, description, capabilities, health_check_fn, timeout_seconds=30.0):
        self._health_checks[name] = health_check_fn
        record = AgentRecord(name=name, description=description, capabilities=capabilities, timeout_seconds=timeout_seconds)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO agents (name, description, capabilities, status, timeout_seconds, registered_at, consecutive_failures, consecutive_successes)
                VALUES (?, ?, ?, 'healthy', ?, ?, 0, 0)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    capabilities=excluded.capabilities,
                    timeout_seconds=excluded.timeout_seconds,
                    status='healthy',
                    consecutive_failures=0,
                    consecutive_successes=0
            """, (record.name, record.description, json.dumps(record.capabilities), record.timeout_seconds, record.registered_at.isoformat()))
            await db.commit()

    async def deregister(self, name):
        self._health_checks.pop(name, None)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM agents WHERE name = ?", (name,))
            await db.commit()

    async def list_all(self) -> list[AgentRecord]:
        """Returns ALL agents including offline (for health monitoring / recovery)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM agents ORDER BY name")
            rows = await cursor.fetchall()
        return [_row_to_record(row) for row in rows]

    async def list_healthy(self) -> list[AgentRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM agents WHERE status != 'offline' ORDER BY name")
            rows = await cursor.fetchall()
        return [_row_to_record(row) for row in rows]

    async def lookup(self, capability: str) -> AgentRecord | None:
        agents = await self.list_healthy()
        for agent in agents:
            if capability in agent.capabilities:
                return agent
        return None

    async def update_liveness(self, name: str, success: bool) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM agents WHERE name = ?", (name,))
            row = await cursor.fetchone()
            if not row:
                return
            record = _row_to_record(row)
            if success:
                record.consecutive_failures = 0
                record.consecutive_successes += 1
                if record.consecutive_successes >= 2:
                    record.status = "healthy"
                elif record.status == "offline":
                    record.status = "degraded"
            else:
                record.consecutive_successes = 0
                record.consecutive_failures += 1
                if record.consecutive_failures >= 5:
                    record.status = "offline"
                elif record.consecutive_failures >= 2:
                    record.status = "degraded"
            record.last_checked_at = datetime.now(timezone.utc)
            await db.execute("""
                UPDATE agents SET status=?, consecutive_failures=?,
                    consecutive_successes=?, last_checked_at=?
                WHERE name=?
            """, (record.status, record.consecutive_failures, record.consecutive_successes, record.last_checked_at.isoformat(), name))
            await db.commit()

    def get_health_check(self, name: str):
        return self._health_checks.get(name)


def _row_to_record(row) -> AgentRecord:
    return AgentRecord(
        name=row["name"],
        description=row["description"],
        capabilities=json.loads(row["capabilities"]),
        status=row["status"],
        timeout_seconds=row["timeout_seconds"],
        last_checked_at=datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None,
        registered_at=datetime.fromisoformat(row["registered_at"]),
        consecutive_failures=row["consecutive_failures"],
        consecutive_successes=row["consecutive_successes"],
    )
