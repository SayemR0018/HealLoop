from __future__ import annotations

from pathlib import Path

from unidiff import PatchSet

from healloop.schemas import FilePatch, FixPlan


class ApplyError(Exception):
    """Raised when a patch cannot be applied safely."""


def _invalidate_bytecode(target: Path) -> None:
    """Drop stale .pyc so same-length edits are not masked by bytecode cache."""
    import os
    import time

    # Bump mtime past second-resolution + size-stable replacements
    now = time.time() + 1.0
    try:
        os.utime(target, (now, now))
    except OSError:
        raise ApplyError(f"could not update mtime for {target}") from None

    cache_dir = target.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    stem = target.stem
    for pyc in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError as exc:
            raise ApplyError(f"could not remove stale bytecode {pyc}: {exc}") from exc


def _resolve_sandboxed(project_root: Path, rel_path: str) -> Path:
    root = project_root.resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ApplyError(f"path escapes project root: {rel_path}")
    return target


def _diff_is_file_add(unified_diff: str) -> bool:
    """Return True when the unified diff creates a new file (--- /dev/null)."""
    for line in unified_diff.splitlines()[:4]:
        if line.startswith("---") and "/dev/null" in line:
            return True
    return False


def _normalize_diff_path(raw: str) -> str:
    clean = raw
    if clean.startswith("a/") or clean.startswith("b/"):
        clean = clean[2:]
    return clean


def _apply_single_diff(
    project_root: Path,
    patch: FilePatch,
    *,
    dry_run: bool = False,
) -> str:
    """Apply one FilePatch; return the new file content (also written unless dry_run)."""
    target = _resolve_sandboxed(project_root, patch.path)
    if not target.exists() and not _diff_is_file_add(patch.unified_diff):
        raise ApplyError(
            f"target file does not exist and diff is not a file add: {patch.path}"
        )

    original = target.read_text(encoding="utf-8") if target.exists() else ""

    try:
        patchset = PatchSet(patch.unified_diff)
    except Exception as exc:
        raise ApplyError(f"invalid unified diff for {patch.path}: {exc}") from exc

    if not patchset:
        raise ApplyError(f"empty patchset for {patch.path}")

    new_content: str | None = None
    for patched_file in patchset:
        for candidate in (patched_file.source_file or "", patched_file.target_file or ""):
            clean = _normalize_diff_path(candidate)
            if clean in ("/dev/null", ""):
                continue
            resolved = _resolve_sandboxed(project_root, clean)
            if resolved != target and resolved.name != Path(patch.path).name:
                raise ApplyError(
                    f"diff path {clean!r} does not match FilePatch.path {patch.path!r}"
                )

        work = original.splitlines(keepends=True)
        offset = 0
        for hunk in patched_file:
            start = hunk.source_start - 1 + offset
            src_lines = [line.value for line in hunk if line.is_context or line.is_removed]
            new_segment: list[str] = []
            old_count = 0
            for line in hunk:
                if line.is_context:
                    new_segment.append(line.value)
                    old_count += 1
                elif line.is_removed:
                    old_count += 1
                elif line.is_added:
                    new_segment.append(line.value)
            expected_old = work[start : start + old_count]
            expected_join = "".join(expected_old)
            src_join = "".join(src_lines)
            if expected_join != src_join:
                exp_stripped = [ln.rstrip("\n\r") for ln in expected_old]
                src_stripped = [ln.rstrip("\n\r") for ln in src_lines]
                if exp_stripped != src_stripped:
                    raise ApplyError(
                        f"hunk context mismatch in {patch.path} at line {hunk.source_start}"
                    )
            work = work[:start] + new_segment + work[start + old_count :]
            offset += len(new_segment) - old_count

        new_content = "".join(work)

    if new_content is None:
        raise ApplyError(f"no file content produced for {patch.path}")

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
        _invalidate_bytecode(target)
    return new_content


def apply_fix_plan(
    plan: FixPlan,
    *,
    project_root: str | Path,
    dry_run: bool = False,
) -> list[str]:
    """Apply all FilePatches all-or-nothing. Returns list of written paths.

    On failure, restores any files already written in this plan.
    """
    root = Path(project_root).resolve()
    # Validate all paths first
    for fp in plan.files:
        _resolve_sandboxed(root, fp.path)

    # Dry-run validate entire plan
    backups: dict[Path, str | None] = {}
    written: list[str] = []
    try:
        for fp in plan.files:
            target = _resolve_sandboxed(root, fp.path)
            backups[target] = target.read_text(encoding="utf-8") if target.exists() else None
            _apply_single_diff(root, fp, dry_run=True)

        if dry_run:
            return [fp.path for fp in plan.files]

        for fp in plan.files:
            _apply_single_diff(root, fp, dry_run=False)
            written.append(fp.path)
        return written
    except Exception:
        # Roll back any writes from this plan
        for w in written:
            target = _resolve_sandboxed(root, w)
            original = backups.get(target)
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_text(original, encoding="utf-8")
        raise
