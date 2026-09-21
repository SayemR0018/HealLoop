from __future__ import annotations

import ast
import re
from pathlib import Path

from healloop.runner import PytestResult
from healloop.schemas import FailureContext, FailureRecord, FileSlice

_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_SHORT_TB_RE = re.compile(r'^(\S+\.py):(\d+)(?::\d+)?:', re.MULTILINE)
MAX_SLICE_LINES = 200
MARGIN = 2
MAX_CONTEXT_CHARS = 24_000


def _enclosing_span(
    tree: ast.AST, lineno: int
) -> tuple[int, int, str | None]:
    """Return (start, end, symbol) for enclosing FunctionDef/ClassDef."""
    best: tuple[int, int, str | None] | None = None
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is None or end is None:
                continue
            if start <= lineno <= end:
                span = end - start
                if best is None or span < (best[1] - best[0]):
                    best = (start, end, node.name)
    if best is None:
        return max(1, lineno - MARGIN), lineno + MARGIN, None
    return best


def slice_for_location(
    file_path: Path,
    lineno: int,
    *,
    margin: int = MARGIN,
    max_lines: int = MAX_SLICE_LINES,
) -> FileSlice | None:
    """Build a FileSlice around lineno using AST enclosing scope."""
    if not file_path.is_file():
        return None
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        start = max(1, lineno - margin)
        end = min(len(lines), lineno + margin)
        source = "".join(lines[start - 1 : end])
        return FileSlice(
            path=str(file_path),
            start_line=start,
            end_line=end,
            source=source,
            symbol=None,
        )

    start, end, symbol = _enclosing_span(tree, lineno)
    start = max(1, start - margin)
    end = min(len(lines), end + margin)
    if end - start + 1 > max_lines:
        # Center on lineno
        half = max_lines // 2
        start = max(1, lineno - half)
        end = min(len(lines), start + max_lines - 1)
        start = max(1, end - max_lines + 1)
    source = "".join(lines[start - 1 : end])
    return FileSlice(
        path=str(file_path),
        start_line=start,
        end_line=end,
        source=source,
        symbol=symbol,
    )


def _locations_from_failure(
    fr: FailureRecord,
) -> list[tuple[str, int]]:
    locs: list[tuple[str, int]] = []
    if fr.file and fr.line:
        locs.append((fr.file, fr.line))
    for match in _FILE_LINE_RE.finditer(fr.traceback or ""):
        fp, ln = match.group(1), int(match.group(2))
        if "site-packages" in fp:
            continue
        locs.append((fp, ln))
    for match in _SHORT_TB_RE.finditer(fr.traceback or ""):
        fp, ln = match.group(1), int(match.group(2))
        if "site-packages" in fp:
            continue
        locs.append((fp, ln))
    # Deduplicate preserving order
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for item in locs:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_context(
    result: PytestResult,
    *,
    project_root: str | Path,
) -> FailureContext:
    """Traceback File/line → enclosing FunctionDef/ClassDef slices."""
    root = Path(project_root).resolve()
    slices: list[FileSlice] = []
    seen_keys: set[tuple[str, int, int]] = set()

    for fr in result.failures:
        for file_str, lineno in _locations_from_failure(fr):
            path = Path(file_str)
            if not path.is_absolute():
                path = (root / path).resolve()
            else:
                path = path.resolve()
            # Prefer paths under project root
            try:
                rel = path.relative_to(root)
                display = str(rel)
            except ValueError:
                display = str(path)

            sl = slice_for_location(path, lineno)
            if sl is None:
                continue
            # Store repo-relative path when possible
            sl = FileSlice(
                path=display,
                start_line=sl.start_line,
                end_line=sl.end_line,
                source=sl.source,
                symbol=sl.symbol,
            )
            key = (sl.path, sl.start_line, sl.end_line)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            slices.append(sl)

    # Cap total characters — drop from the end (lowest priority)
    total = sum(len(s.source) for s in slices)
    while total > MAX_CONTEXT_CHARS and slices:
        dropped = slices.pop()
        total -= len(dropped.source)

    return FailureContext(
        project_root=str(root),
        failures=list(result.failures),
        slices=slices,
        pytest_stdout=result.stdout,
        pytest_stderr=result.stderr,
        exit_code=result.exit_code,
    )


# Alias used by loop
build = build_context
