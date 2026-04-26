"""Request/response schemas. Aligned with the JobStore.Job dataclass."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobView(BaseModel):
    id: str
    hash: str
    run_id: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    job: JobView
    existing: bool


class JobListResponse(BaseModel):
    jobs: list[JobView]
