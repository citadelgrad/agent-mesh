from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Session state key conventions:
# 'task_decomposition'     → TaskDecomposition JSON  — written by RouterAgent, read by ParallelDispatcher
# 'result_{agent_name}'   → SpecialistResult JSON   — written by ParallelDispatcher, read by SynthesizerAgent
# 'mesh_response'          → MeshResponse JSON       — written by SynthesizerAgent, read by main.py


class AgentRecord(BaseModel):
    name: str
    description: str
    capabilities: list[str]
    status: Literal["healthy", "degraded", "offline"] = "healthy"
    timeout_seconds: float = 30.0
    last_checked_at: datetime | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0
    consecutive_successes: int = 0


class Subtask(BaseModel):
    capability: str
    agent_name: str
    instruction: str


class TaskDecomposition(BaseModel):
    subtasks: list[Subtask]
    original_task: str


class SpecialistResult(BaseModel):
    agent_name: str
    capability: str
    output: str
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0


class MeshResponse(BaseModel):
    answer: str = Field(description="Complete synthesized answer to the original task")
    sources: list[str] = Field(description="Agent names that contributed to this answer")
    partial: bool = Field(description="True when one or more specialists were unavailable")
    unavailable_capabilities: list[str] = Field(
        description="List of capabilities that could not be fulfilled due to offline agents",
        default_factory=list,
    )
