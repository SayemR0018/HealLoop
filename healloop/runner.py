from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from healloop.schemas import FailureRecord

_NODE_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)", re.MULTILINE)
_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_SHORT_TB_RE = re.compile(r'^(\S+\.py):(\d+)(?::\d+)?:', re.MULTILINE)
_SHORT_SUMMARY_RE = re.compile(
    r"=+\s+\d+\s+failed.*?=+\s*$", re.MULTILINE | re.DOTALL
)


def _clear_pycache(root: Path) -> None:
    """Remove __pycache__ trees so pytest always loads current sources."""
    import shutil

    for cache in root.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)


@dataclass
class PytestResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    failures: list[FailureRecord] = field(default_factory=list)


def _extract_failures(stdout: str, stderr: str) -> list[FailureRecord]:
    combined = stdout + "\n" + stderr
    failures: list[FailureRecord] = []
    seen: set[str] = set()

    # Parse FAILED nodeids from summary / progress lines
    for match in _NODE_RE.finditer(combined):
        nodeid = match.group(2).rstrip()
        if nodeid in seen:
            continue
        seen.add(nodeid)
        failures.append(FailureRecord(nodeid=nodeid, traceback=""))

    # Also catch "test_file.py::test_name FAILED" style from verbose
    for match in re.finditer(r"^(\S+::\S+)\s+FAILED", combined, re.MULTILINE):
        nodeid = match.group(1)
        if nodeid not in seen:
            seen.add(nodeid)
            failures.append(FailureRecord(nodeid=nodeid, traceback=""))

    # Attach traceback blocks from FAILURES section
    fail_section = re.split(r"={5,}\s*FAILURES\s*={5,}", combined, maxsplit=1)
    tb_blob = fail_section[1] if len(fail_section) > 1 else combined

    # Split per test heading like _____ test_name _____
    blocks = re.split(r"_{5,}\s+.+\s+_{5,}", tb_blob)
    headings = re.findall(r"_{5,}\s+(.+?)\s+_{5,}", tb_blob)

    if headings and len(blocks) > 1:
        for heading, block in zip(headings, blocks[1:], strict=False):
            nodeid_guess = heading.strip()
            file_path: str | None = None
            line_no: int | None = None
            # Prefer last File "…", line N in the block that is not site-packages
            for fm in _FILE_LINE_RE.finditer(block):
                fp, ln = fm.group(1), int(fm.group(2))
                if "site-packages" in fp or "pytest" in Path(fp).parts:
                    continue
                file_path, line_no = fp, ln
            if file_path is None:
                for fm in _SHORT_TB_RE.finditer(block):
                    fp, ln = fm.group(1), int(fm.group(2))
                    if "site-packages" in fp:
                        continue
                    file_path, line_no = fp, ln
            # Match to existing failure by suffix
            matched = False
            for fr in failures:
                if nodeid_guess in fr.nodeid or fr.nodeid.endswith(nodeid_guess):
                    fr.traceback = block.strip()
                    fr.file = file_path
                    fr.line = line_no
                    matched = True
                    break
            if not matched:
                # Try to reconstruct nodeid from file
                nid = nodeid_guess
                if file_path:
                    nid = f"{Path(file_path).name}::{nodeid_guess}"
                if nid not in seen:
                    seen.add(nid)
                    failures.append(
                        FailureRecord(
                            nodeid=nid,
                            traceback=block.strip(),
                            file=file_path,
                            line=line_no,
                        )
                    )
    else:
        # Fallback: enrich first failure with any File/line found
        for fr in failures:
            if fr.traceback:
                continue
            for fm in _FILE_LINE_RE.finditer(combined):
                fp, ln = fm.group(1), int(fm.group(2))
                if "site-packages" in fp:
                    continue
                fr.file = fp
                fr.line = ln
                fr.traceback = combined[-4000:]
                break

    # If still empty but exit != 0, synthesize a record
    if not failures:
        file_path = None
        line_no = None
        for fm in _FILE_LINE_RE.finditer(combined):
            fp, ln = fm.group(1), int(fm.group(2))
            if "site-packages" not in fp:
                file_path, line_no = fp, ln
        failures.append(
            FailureRecord(
                nodeid="<unknown>",
                traceback=combined[-4000:],
                file=file_path,
                line=line_no,
            )
        )
    return failures


def run_pytest(
    target: str | Path,
    *,
    project_root: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> PytestResult:
    """Invoke pytest as a subprocess and capture failures."""
    target_path = Path(target)
    root = Path(project_root) if project_root else (
        target_path if target_path.is_dir() else target_path.parent
    )
    root = root.resolve()

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(target),
        "-v",
        "--tb=short",
        "--no-header",
    ]
    if extra_args:
        cmd.extend(extra_args)

    _clear_pycache(root)

    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    ok = proc.returncode == 0
    failures: list[FailureRecord] = []
    if not ok:
        failures = _extract_failures(stdout, stderr)
    return PytestResult(
        ok=ok,
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        failures=failures,
    )
