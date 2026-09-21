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
from urllib.parse import unquote

_ROOT = Path(__file__).resolve().parent.parent
_WEB_ROOT = (_ROOT / "web").resolve()
_FIXTURE_FILES = ("buggy_math.py", "test_buggy_math.py")
_INTENTIONAL_BUG = "return a - b"
_MAX_BODY_BYTES = 1_048_576
_HEAL_PATHS = {"/api/heal", "/api/heal.py"}
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


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

import pytest  # noqa: E402, F401  — keep pytest in the Vercel function bundle
from healloop.loop import run_loop  # noqa: E402
from healloop.schemas import LoopStatus, Scorecard  # noqa: E402

_last_pytest: dict[str, object] = {"code": None, "text": ""}


def _capture_pytest_output() -> None:
    """Remember the last pytest subprocess output for a failed mock heal."""
    import healloop.runner as runner_mod

    if getattr(runner_mod.run_pytest, "_healloop_capture", False):
        return
    original = runner_mod.run_pytest

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        text = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
        _last_pytest["code"] = result.exit_code
        _last_pytest["text"] = text[-1500:]
        return result

    wrapped._healloop_capture = True  # type: ignore[attr-defined]
    runner_mod.run_pytest = wrapped


_capture_pytest_output()


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


def _request_path(raw: str) -> str:
    """Return the URL path without query, fragment, or a trailing slash."""
    path = unquote(raw.split("?", 1)[0].split("#", 1)[0])
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def _is_heal_path(path: str) -> bool:
    return path in _HEAL_PATHS


def _static_file(path: str) -> Path | None:
    """Map `/` and `/styles.css` (also `/web/...`) onto files under web/."""
    rel = "index.html" if path == "/" else path.lstrip("/")
    if rel.startswith("web/"):
        rel = rel[len("web/") :]
    if not rel or rel.endswith("/"):
        return None
    candidate = (_WEB_ROOT / rel).resolve()
    if not candidate.is_relative_to(_WEB_ROOT) or not candidate.is_file():
        return None
    return candidate


class handler(BaseHTTPRequestHandler):
    """Vercel Python entrypoint (`handler` + BaseHTTPRequestHandler).

    The Python runtime routes every request to this entrypoint, so `/`
    serves the static shell from ``web/`` and only ``/api/heal`` runs the
    mock loop. ``vercel.json`` routes stay in place for the same split.
    """

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if _is_heal_path(path):
            self._respond_heal()
            return
        self._respond_static(path)

    def do_POST(self) -> None:
        self._discard_body()
        path = _request_path(self.path)
        if not _is_heal_path(path):
            self._send(404, _json_bytes(json.dumps({"error": "not found"})))
            return
        self._respond_heal()

    def do_HEAD(self) -> None:
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

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
        payload = json.loads(card.model_dump_json())
        if not card.passed:
            payload["pytest_exit"] = _last_pytest.get("code")
            payload["pytest_output"] = _last_pytest.get("text")
            print(payload["pytest_output"], flush=True)
        self._send(200, _json_bytes(json.dumps(payload, indent=2)))

    def _respond_static(self, path: str) -> None:
        target = _static_file(path)
        if target is None:
            self._send(404, _json_bytes(json.dumps({"error": "not found"})))
            return
        body = target.read_bytes()
        content_type = _STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, body, content_type=content_type, cache="public, max-age=300")

    def _send(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
        cache: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body and not getattr(self, "_head_only", False):
            self.wfile.write(body)


def main() -> int:
    """Local smoke: print the mock Scorecard and exit 0 only when green."""
    card = run_mock_heal()
    sys.stdout.write(card.model_dump_json(indent=2) + "\n")
    return 0 if card.status is LoopStatus.green and card.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
