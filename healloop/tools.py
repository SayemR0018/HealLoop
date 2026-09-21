from __future__ import annotations

"""HealLoop agentic tool surface for GPT-6 (run_pytest / read_slice / submit_fix_plan)."""

import json
from pathlib import Path
from typing import Any, Callable

from healloop import runner
from healloop.schemas import FixPlan

MAX_SLICE_LINES = 400


class ToolError(Exception):
    """Raised when a tool call is invalid or sandboxed out."""


def _resolve_sandboxed(project_root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* under *project_root*; reject abs / ``..`` escapes."""
    if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise ToolError(f"path escapes project root or is absolute: {rel_path!r}")
    root = project_root.resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ToolError(f"path escapes project root: {rel_path!r}")
    return target


def tool_run_pytest(target: str, *, project_root: Path) -> dict[str, Any]:
    """Run pytest on *target* under the sandbox root; return a JSON-able dict."""
    root = project_root.resolve()
    # Allow relative targets under root; reject escapes
    if target.startswith("/") or ".." in Path(target).parts:
        # Absolute only OK if still under root after resolve
        tpath = Path(target).resolve()
        if not tpath.is_relative_to(root):
            raise ToolError(f"pytest target escapes project root: {target!r}")
        target_arg = str(tpath)
    else:
        tpath = _resolve_sandboxed(root, target)
        target_arg = str(tpath)
    result = runner.run_pytest(target_arg, project_root=root)
    return {
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-4000:],
        "failures": [
            {
                "nodeid": f.nodeid,
                "file": f.file,
                "line": f.line,
                "traceback": (f.traceback or "")[-2000:],
            }
            for f in result.failures
        ],
    }


def tool_read_slice(
    path: str,
    start_line: int,
    end_line: int,
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Read a 1-indexed inclusive source slice under the sandbox."""
    if start_line < 1 or end_line < start_line:
        raise ToolError(
            f"invalid line range: start_line={start_line}, end_line={end_line}"
        )
    if end_line - start_line + 1 > MAX_SLICE_LINES:
        raise ToolError(f"slice too large; max {MAX_SLICE_LINES} lines")
    target = _resolve_sandboxed(project_root, path)
    if not target.is_file():
        raise ToolError(f"file not found: {path!r}")
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    # 1-indexed inclusive
    start_idx = start_line - 1
    end_idx = min(end_line, len(lines))
    if start_idx >= len(lines):
        raise ToolError(
            f"start_line {start_line} beyond end of file ({len(lines)} lines)"
        )
    chunk = "".join(lines[start_idx:end_idx])
    return {
        "path": path,
        "start_line": start_line,
        "end_line": end_idx,
        "total_lines": len(lines),
        "source": chunk,
    }


def tool_submit_fix_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate arguments as FixPlan and return a confirmation payload."""
    plan = FixPlan.model_validate(arguments)
    return {
        "accepted": True,
        "plan": plan.model_dump(mode="json"),
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_pytest",
            "description": (
                "Run pytest on a target path or node under the project root. "
                "Returns ok/exit_code/stdout/stderr/failures. No network."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Repo-relative path or pytest node id",
                    },
                },
                "required": ["target"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_slice",
            "description": (
                "Read a 1-indexed inclusive source slice from a file under the "
                "project root (sandboxed; rejects .. and absolute escapes)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative file path",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-indexed start line",
                        "minimum": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-indexed end line (inclusive)",
                        "minimum": 1,
                    },
                },
                "required": ["path", "start_line", "end_line"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_fix_plan",
            "description": (
                "Submit a validated FixPlan (rationale, risk, files with "
                "unified diffs, confidence). Call this when ready to apply."
            ),
            "parameters": FixPlan.model_json_schema(),
        },
    },
]


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "run_pytest": lambda arguments, project_root: tool_run_pytest(
        str(arguments["target"]), project_root=project_root
    ),
    "read_slice": lambda arguments, project_root: tool_read_slice(
        str(arguments["path"]),
        int(arguments["start_line"]),
        int(arguments["end_line"]),
        project_root=project_root,
    ),
    "submit_fix_plan": lambda arguments, project_root: tool_submit_fix_plan(
        arguments
    ),
}


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """Dispatch a tool by name; return a JSON string result (errors included)."""
    root = Path(project_root).resolve()
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool: {name!r}"})
    try:
        result = handler(arguments, project_root=root)
        return json.dumps(result)
    except ToolError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — surface to model as tool error
        return json.dumps({"error": f"{type(exc).__name__}: {exc}")
