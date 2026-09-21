from __future__ import annotations

import json
from pathlib import Path

from healloop.client import MockLLM
from healloop import apply as apply_mod
from healloop.schemas import FailureContext, FailureRecord
from healloop.tools import TOOL_DEFINITIONS, execute_tool


def test_tool_definitions_register() -> None:
    assert isinstance(TOOL_DEFINITIONS, list)
    assert len(TOOL_DEFINITIONS) >= 3
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "run_pytest" in names
    assert "read_slice" in names
    assert "submit_fix_plan" in names
    # submit_fix_plan parameters come from FixPlan schema
    submit = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "submit_fix_plan")
    params = submit["function"]["parameters"]
    assert "properties" in params
    assert "rationale" in params["properties"]
    assert "files" in params["properties"]


def test_execute_read_slice_and_run_pytest(tmp_path: Path) -> None:
    (tmp_path / "buggy_math.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a - b  # intentional bug\n",
        encoding="utf-8",
    )
    (tmp_path / "test_buggy_math.py").write_text(
        "from buggy_math import add\n\n"
        "def test_add_positive() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # read_slice
    raw = execute_tool(
        "read_slice",
        {"path": "buggy_math.py", "start_line": 1, "end_line": 2},
        project_root=tmp_path,
    )
    payload = json.loads(raw)
    assert "error" not in payload
    assert "return a - b" in payload["source"]
    assert payload["path"] == "buggy_math.py"

    # sandbox reject
    bad = json.loads(
        execute_tool(
            "read_slice",
            {"path": "../etc/passwd", "start_line": 1, "end_line": 1},
            project_root=tmp_path,
        )
    )
    assert "error" in bad

    # run_pytest — expect failure on broken fixture
    fail_raw = execute_tool(
        "run_pytest",
        {"target": str(tmp_path)},
        project_root=tmp_path,
    )
    fail_payload = json.loads(fail_raw)
    assert fail_payload.get("ok") is False
    assert fail_payload.get("exit_code", 1) != 0

    # MockLLM plan + apply → green
    ctx = FailureContext(
        project_root=str(tmp_path),
        failures=[
            FailureRecord(
                nodeid="test_buggy_math.py::test_add_positive",
                traceback="AssertionError",
                file=str(tmp_path / "buggy_math.py"),
                line=2,
            )
        ],
        slices=[],
        pytest_stdout=fail_payload.get("stdout", ""),
        pytest_stderr=fail_payload.get("stderr", ""),
        exit_code=int(fail_payload.get("exit_code", 1)),
    )
    plan, tokens = MockLLM.next_plan(ctx)
    assert tokens == 100
    apply_mod.apply_fix_plan(plan, project_root=tmp_path)

    green_raw = execute_tool(
        "run_pytest",
        {"target": str(tmp_path)},
        project_root=tmp_path,
    )
    green = json.loads(green_raw)
    assert green.get("ok") is True
    assert green.get("failures") == []


def test_submit_fix_plan_validates(tmp_path: Path) -> None:
    bad = json.loads(
        execute_tool(
            "submit_fix_plan",
            {"rationale": "x", "risk": "low", "files": [], "confidence": 0.5},
            project_root=tmp_path,
        )
    )
    assert "error" in bad

    good_args = {
        "rationale": "fix add",
        "risk": "low",
        "files": [
            {
                "path": "buggy_math.py",
                "unified_diff": (
                    "--- a/buggy_math.py\n"
                    "+++ b/buggy_math.py\n"
                    "@@ -1,2 +1,2 @@\n"
                    " def add(a: int, b: int) -> int:\n"
                    "-    return a - b\n"
                    "+    return a + b\n"
                ),
            }
        ],
        "confidence": 0.9,
    }
    good = json.loads(
        execute_tool("submit_fix_plan", good_args, project_root=tmp_path)
    )
    assert good.get("accepted") is True
    assert good["plan"]["files"][0]["path"] == "buggy_math.py"


def test_unknown_tool(tmp_path: Path) -> None:
    raw = execute_tool("not_a_tool", {}, project_root=tmp_path)
    assert "error" in json.loads(raw)
