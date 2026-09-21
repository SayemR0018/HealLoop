from __future__ import annotations

from pathlib import Path

import pytest

from healloop.apply import ApplyError, apply_fix_plan
from healloop.schemas import FilePatch, FixPlan, RiskLevel


def _plan(path: str, diff: str) -> FixPlan:
    return FixPlan(
        rationale="test",
        risk=RiskLevel.low,
        files=[FilePatch(path=path, unified_diff=diff)],
        confidence=0.8,
    )


def test_apply_simple_change(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    diff = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n"
    )
    apply_fix_plan(_plan("sample.py", diff), project_root=tmp_path)
    assert "return a + b" in target.read_text(encoding="utf-8")


def test_sandbox_rejects_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_healloop_test.py"
    # Path validator on FilePatch already blocks .. ; craft via model_construct
    patch = FilePatch.model_construct(
        path="../outside_healloop_test.py",
        unified_diff=(
            "--- a/../outside_healloop_test.py\n"
            "+++ b/../outside_healloop_test.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        ),
    )
    plan = FixPlan.model_construct(
        rationale="evil",
        risk=RiskLevel.high,
        files=[patch],
        confidence=0.1,
    )
    with pytest.raises(ApplyError):
        apply_fix_plan(plan, project_root=tmp_path)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    original = "line1\nline2\n"
    target.write_text(original, encoding="utf-8")
    diff = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-line1\n"
        "+LINE1\n"
        " line2\n"
    )
    apply_fix_plan(_plan("sample.py", diff), project_root=tmp_path, dry_run=True)
    assert target.read_text(encoding="utf-8") == original
