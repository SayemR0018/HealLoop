from __future__ import annotations

import pytest
from pydantic import ValidationError

from healloop.schemas import (
    FilePatch,
    FixPlan,
    LoopStatus,
    RiskLevel,
    Scorecard,
)


def test_file_patch_rejects_absolute() -> None:
    with pytest.raises(ValidationError):
        FilePatch(path="/etc/passwd", unified_diff="--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b\n")


def test_file_patch_rejects_dotdot() -> None:
    with pytest.raises(ValidationError):
        FilePatch(
            path="../secrets.py",
            unified_diff="--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b\n",
        )


def test_file_patch_rejects_nested_dotdot() -> None:
    with pytest.raises(ValidationError):
        FilePatch(
            path="foo/../../etc/passwd",
            unified_diff="--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b\n",
        )


def test_fix_plan_requires_files() -> None:
    with pytest.raises(ValidationError):
        FixPlan(rationale="x", risk=RiskLevel.low, files=[])


def test_fix_plan_valid() -> None:
    plan = FixPlan(
        rationale="fix add",
        risk=RiskLevel.low,
        files=[
            FilePatch(
                path="buggy_math.py",
                unified_diff="--- a/buggy_math.py\n+++ b/buggy_math.py\n@@ -1,2 +1,2 @@\n",
            )
        ],
        confidence=0.9,
    )
    assert plan.confidence == 0.9
    assert plan.risk is RiskLevel.low


def test_scorecard_status_enum() -> None:
    card = Scorecard(
        status=LoopStatus.green,
        iterations=1,
        max_iterations=5,
        tokens_used=100,
        token_budget=5000,
        passed=True,
        model="gpt-6",
        fixture_or_target="examples/broken",
    )
    assert card.status == LoopStatus.green
    assert card.model_dump()["status"] == "green"
