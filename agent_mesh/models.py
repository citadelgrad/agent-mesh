from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Session state key conventions:
# 'task_decomposition'     → TaskDecomposition JSON  — written by RouterAgent
# 'result_{agent_name}'   → SpecialistResult JSON   — written by ParallelDispatcher
# 'mesh_response'          → MeshResponse JSON       — written by SynthesizerAgent


class AgentRecord(BaseModel):
    """Legacy: used by registry.py (optional local fallback). Not on the active routing path."""
    name: str
    description: str
    capabilities: list[str]
    timeout_seconds: float = 30.0
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Subtask(BaseModel):
    capability: str
    agent_name: str
    instruction: str


class TaskDecomposition(BaseModel):
    subtasks: list[Subtask]
    original_task: str


ErrorKind = Literal["timeout", "http_error", "card_unreachable", "capability_mismatch", "unknown"]


class SpecialistResult(BaseModel):
    agent_name: str
    capability: str
    output: str
    success: bool
    error: str | None = None
    error_kind: ErrorKind | None = None
    duration_seconds: float = 0.0


class MeshResponse(BaseModel):
    answer: str = Field(description="Complete synthesized answer to the original task")
    sources: list[str] = Field(description="Agent names that contributed to this answer")
    partial: bool = Field(description="True when one or more specialists were unavailable")
    unavailable_capabilities: list[str] = Field(
        description="List of capabilities that could not be fulfilled",
        default_factory=list,
    )
