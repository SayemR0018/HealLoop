from __future__ import annotations

from pathlib import Path

from healloop.runner import run_pytest


def test_runner_captures_failure(tmp_path: Path) -> None:
    (tmp_path / "buggy_math.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a - b\n",
        encoding="utf-8",
    )
    (tmp_path / "test_buggy_math.py").write_text(
        "from buggy_math import add\n\n"
        "def test_add_positive() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    result = run_pytest(str(tmp_path), project_root=tmp_path)
    assert result.ok is False
    assert result.exit_code != 0
    assert len(result.failures) >= 1
    assert any("test_add" in f.nodeid for f in result.failures)


def test_runner_pass(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "from ok import f\n\ndef test_f() -> None:\n    assert f() == 1\n",
        encoding="utf-8",
    )
    result = run_pytest(str(tmp_path), project_root=tmp_path)
    assert result.ok is True
    assert result.failures == []
