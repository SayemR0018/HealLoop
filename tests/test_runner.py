from __future__ import annotations

import os
from pathlib import Path

from healloop import runner
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


def test_runner_forwards_sys_path_to_pytest(tmp_path: Path, monkeypatch) -> None:
    sentinel = str(tmp_path / "runtime-site")
    monkeypatch.syspath_prepend(sentinel)
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = run_pytest(tmp_path, project_root=tmp_path)
    assert result.ok is True
    env = captured["env"]
    assert isinstance(env, dict)
    assert sentinel in env["PYTHONPATH"].split(os.pathsep)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_runner_pass(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "from ok import f\n\ndef test_f() -> None:\n    assert f() == 1\n",
        encoding="utf-8",
    )
    result = run_pytest(str(tmp_path), project_root=tmp_path)
    assert result.ok is True
    assert result.failures == []
