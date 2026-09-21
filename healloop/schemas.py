from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class FilePatch(BaseModel):
    path: str = Field(..., description="Repo-relative path under project root")
    unified_diff: str = Field(..., min_length=1)

    @field_validator("path")
    @classmethod
    def no_abs_or_dotdot(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("path must be relative and must not contain ..")
        return v


class FixPlan(BaseModel):
    """Structured model output — enforced via response_format / parse."""

    rationale: str
    risk: RiskLevel
    files: list[FilePatch] = Field(..., min_length=1)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class FailureRecord(BaseModel):
    nodeid: str
    traceback: str
    file: str | None = None
    line: int | None = None


class FileSlice(BaseModel):
    path: str
    start_line: int
    end_line: int
    source: str
    symbol: str | None = None


class FailureContext(BaseModel):
    project_root: str
    failures: list[FailureRecord]
    slices: list[FileSlice]
    pytest_stdout: str
    pytest_stderr: str
    exit_code: int


class LoopStatus(str, Enum):
    green = "green"
    budget = "budget"
    max_iter = "max_iter"
    error = "error"
    dry_run = "dry_run"


class IterationRecord(BaseModel):
    index: int
    status_before: Literal["fail", "pass"]
    tokens_used: int = 0
    applied: bool = False
    fix_plan: FixPlan | None = None
    error: str | None = None


class Scorecard(BaseModel):
    status: LoopStatus
    iterations: int
    max_iterations: int
    tokens_used: int
    token_budget: int
    passed: bool
    remaining_failures: list[str] = Field(default_factory=list)
    history: list[IterationRecord] = Field(default_factory=list)
    model: str
    fixture_or_target: str
