import aiosqlite
import json
from pathlib import Path
from datetime import datetime
from agent_mesh.models import AgentRecord


class CapabilityRegistry:
    """Legacy local persistence fallback. Not on the active routing path — use catalog.py."""

    def __init__(self, db_path: str = "./data/mesh.db"):
        self._db_path = db_path

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    timeout_seconds REAL NOT NULL DEFAULT 30.0,
                    registered_at TEXT NOT NULL
                )
            """)
            await db.commit()

    async def register(
        self, name: str, description: str, capabilities: list[str], timeout_seconds: float = 30.0
    ) -> None:
        record = AgentRecord(
            name=name, description=description,
            capabilities=capabilities, timeout_seconds=timeout_seconds,
        )
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO agents (name, description, capabilities, timeout_seconds, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    capabilities=excluded.capabilities,
                    timeout_seconds=excluded.timeout_seconds
            """, (
                record.name, record.description,
                json.dumps(record.capabilities), record.timeout_seconds,
                record.registered_at.isoformat(),
            ))
            await db.commit()

    async def deregister(self, name: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM agents WHERE name = ?", (name,))
            await db.commit()

    async def list_all(self) -> list[AgentRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM agents ORDER BY name")
            rows = await cursor.fetchall()
        return [_row_to_record(row) for row in rows]

    async def lookup(self, capability: str) -> AgentRecord | None:
        agents = await self.list_all()
        return next((a for a in agents if capability in a.capabilities), None)


def _row_to_record(row) -> AgentRecord:
    return AgentRecord(
        name=row["name"],
        description=row["description"],
        capabilities=json.loads(row["capabilities"]),
        timeout_seconds=row["timeout_seconds"],
        registered_at=datetime.fromisoformat(row["registered_at"]),
    )
