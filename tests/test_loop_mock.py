from __future__ import annotations

from pathlib import Path

from healloop.loop import run_loop
from healloop.schemas import LoopStatus


def _seed_fixture(dir_path: Path) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "buggy_math.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a - b  # intentional bug — HealLoop must change to a + b\n",
        encoding="utf-8",
    )
    (dir_path / "test_buggy_math.py").write_text(
        "from buggy_math import add\n\n"
        "def test_add_positive() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )


def test_loop_mock_greens_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "broken"
    _seed_fixture(fixture)
    card = run_loop(
        fixture,
        project_root=fixture,
        max_iter=3,
        token_budget=5000,
        mock=True,
        dry_run=False,
    )
    assert card.status == LoopStatus.green
    assert card.passed is True
    assert card.tokens_used >= 100
    fixed = (fixture / "buggy_math.py").read_text(encoding="utf-8")
    assert "return a + b" in fixed
    assert "return a - b" not in fixed


def test_loop_dry_run_no_write(tmp_path: Path) -> None:
    fixture = tmp_path / "broken"
    _seed_fixture(fixture)
    original = (fixture / "buggy_math.py").read_text(encoding="utf-8")
    card = run_loop(
        fixture,
        project_root=fixture,
        max_iter=3,
        token_budget=5000,
        mock=True,
        dry_run=True,
    )
    assert card.status == LoopStatus.dry_run
    assert (fixture / "buggy_math.py").read_text(encoding="utf-8") == original


def test_loop_budget(tmp_path: Path) -> None:
    fixture = tmp_path / "broken"
    _seed_fixture(fixture)
    card = run_loop(
        fixture,
        project_root=fixture,
        max_iter=5,
        token_budget=0,
        mock=True,
        dry_run=False,
    )
    assert card.status == LoopStatus.budget
    assert card.passed is False
