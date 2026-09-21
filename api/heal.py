"""Vercel function: mock-only Scorecard for the examples/broken fixture.

Live OpenAI is refused. HEALLOOP_MOCK is forced before HealLoop is imported,
and any API key in the process environment is discarded.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_FILES = ("buggy_math.py", "test_buggy_math.py")
_INTENTIONAL_BUG = "return a - b"
_MAX_BODY_BYTES = 1_048_576


def _refuse_live_openai() -> None:
    """Force the mock healer and drop credentials that could reach GPT-6."""
    os.environ["HEALLOOP_MOCK"] = "1"
    os.environ["HEALLOOP_AGENTIC"] = "0"
    os.environ["HEALLOOP_USE_CODEX"] = "0"
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("OPENAI_BASE_URL", None)


def _ensure_package_path() -> None:
    """Make the repo-root `healloop` package importable inside the function."""
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_refuse_live_openai()
_ensure_package_path()

from healloop.loop import run_loop  # noqa: E402
from healloop.schemas import LoopStatus, Scorecard  # noqa: E402


def _stage_fixture() -> Path:
    """Copy examples/broken into a writable temp dir, preserving the bug."""
    source = _ROOT / "examples" / "broken"
    buggy = source / "buggy_math.py"
    if not buggy.is_file():
        raise FileNotFoundError(f"fixture missing: {buggy}")
    original = buggy.read_text(encoding="utf-8")
    if _INTENTIONAL_BUG not in original:
        raise RuntimeError(
            "examples/broken/buggy_math.py lost the intentional bug "
            f"{_INTENTIONAL_BUG!r}"
        )

    stage = Path(tempfile.mkdtemp(prefix="healloop-demo-"))
    try:
        for name in _FIXTURE_FILES:
            src = source / name
            if not src.is_file():
                raise FileNotFoundError(f"fixture missing: {src}")
            shutil.copyfile(src, stage / name)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return stage


def run_mock_heal() -> Scorecard:
    """Run the closed loop on a temp copy of examples/broken. Never calls GPT-6."""
    _refuse_live_openai()
    if os.environ.get("HEALLOOP_MOCK") != "1":
        raise RuntimeError("HEALLOOP_MOCK must be 1; live OpenAI is disabled")
    if os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must not be set for the mock heal")

    stage = _stage_fixture()
    try:
        return run_loop(
            stage,
            project_root=stage,
            max_iter=3,
            token_budget=5_000,
            mock=True,
            dry_run=False,
            write_report=False,
            agentic=False,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _json_bytes(payload: str) -> bytes:
    if not payload.endswith("\n"):
        payload += "\n"
    return payload.encode("utf-8")


class handler(BaseHTTPRequestHandler):
    """Vercel Python entrypoint (`handler` + BaseHTTPRequestHandler)."""

    def do_GET(self) -> None:
        self._respond_heal()

    def do_POST(self) -> None:
        self._discard_body()
        self._respond_heal()

    def do_OPTIONS(self) -> None:
        self._send(204, b"")

    def _discard_body(self) -> None:
        raw = self.headers.get("Content-Length", "0")
        try:
            length = int(raw)
        except (TypeError, ValueError):
            length = 0
        remaining = min(max(length, 0), _MAX_BODY_BYTES)
        while remaining > 0:
            chunk = self.rfile.read(remaining)
            if not chunk:
                break
            remaining -= len(chunk)

    def _respond_heal(self) -> None:
        try:
            card = run_mock_heal()
        except Exception as exc:
            traceback.print_exc()
            message = str(exc) or exc.__class__.__name__
            self._send(500, _json_bytes(json.dumps({"error": message})))
            return

        print(
            f"healloop mock heal status={card.status.value} "
            f"iterations={card.iterations} passed={card.passed}",
            flush=True,
        )
        self._send(200, _json_bytes(card.model_dump_json(indent=2)))

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body:
            self.wfile.write(body)


def main() -> int:
    """Local smoke: print the mock Scorecard and exit 0 only when green."""
    card = run_mock_heal()
    sys.stdout.write(card.model_dump_json(indent=2) + "\n")
    return 0 if card.status is LoopStatus.green and card.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
