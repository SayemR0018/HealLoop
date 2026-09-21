from __future__ import annotations

from pathlib import Path

from healloop.ast_context import build_context, slice_for_location
from healloop.runner import PytestResult
from healloop.schemas import FailureRecord


def test_slice_enclosing_function(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text(
        "class C:\n"
        "    def foo(self):\n"
        "        x = 1\n"
        "        return x\n"
        "\n"
        "def other():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    sl = slice_for_location(src, 3)
    assert sl is not None
    assert sl.symbol == "foo"
    assert "def foo" in sl.source
    assert "x = 1" in sl.source
    # ±2 margin may touch nearby lines; symbol must still be the enclosing def


def test_build_context_from_failure(tmp_path: Path) -> None:
    src = tmp_path / "buggy.py"
    src.write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    tb = (
        f'Traceback (most recent call last):\n'
        f'  File "{src}", line 2, in add\n'
        f"    return a - b\n"
        f"AssertionError\n"
    )
    result = PytestResult(
        ok=False,
        exit_code=1,
        stdout="FAILED",
        stderr="",
        failures=[
            FailureRecord(
                nodeid="buggy.py::test_x",
                traceback=tb,
                file=str(src),
                line=2,
            )
        ],
    )
    ctx = build_context(result, project_root=tmp_path)
    assert ctx.exit_code == 1
    assert len(ctx.slices) >= 1
    assert "return a - b" in ctx.slices[0].source
