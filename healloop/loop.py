from __future__ import annotations

import os
from pathlib import Path

from healloop import apply as apply_mod
from healloop import ast_context, client as client_mod
from healloop import report as report_mod
from healloop import runner
from healloop.schemas import (
    IterationRecord,
    LoopStatus,
    Scorecard,
)

DEFAULT_MODEL = os.environ.get("HEALLOOP_MODEL", "gpt-6")


def run_loop(
    target: str | Path,
    *,
    project_root: str | Path | None = None,
    max_iter: int = 5,
    token_budget: int = 50_000,
    mock: bool = False,
    dry_run: bool = False,
    model: str = DEFAULT_MODEL,
    write_report: bool = True,
    agentic: bool | None = None,
) -> Scorecard:
    """Closed-loop pytest healer control flow (ARCH_SPEC §6)."""
    target_path = Path(target)
    if project_root is None:
        root = Path.cwd().resolve()
    else:
        root = Path(project_root).resolve()
    # Resolve relative targets against cwd for pytest invocation
    _ = target_path

    use_mock = mock or os.environ.get("HEALLOOP_MOCK", "0") == "1"
    if agentic is None:
        agentic = os.environ.get("HEALLOOP_AGENTIC", "0") == "1"
    history: list[IterationRecord] = []
    tokens = 0
    index = 0
    fixture_label = str(target)

    try:
        oa_client = client_mod.build_client(mock=use_mock)
    except RuntimeError as exc:
        card = Scorecard(
            status=LoopStatus.error,
            iterations=0,
            max_iterations=max_iter,
            tokens_used=0,
            token_budget=token_budget,
            passed=False,
            remaining_failures=[str(exc)],
            history=[],
            model=model if not use_mock else "mock",
            fixture_or_target=fixture_label,
        )
        if write_report:
            report_mod.write_scorecard(card, project_root=root)
        return card

    while True:
        result = runner.run_pytest(target, project_root=root)
        if result.ok:
            card = Scorecard(
                status=LoopStatus.green,
                iterations=index,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=True,
                remaining_failures=[],
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        remaining = [f.nodeid for f in result.failures]

        if index >= max_iter:
            card = Scorecard(
                status=LoopStatus.max_iter,
                iterations=index,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=False,
                remaining_failures=remaining,
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        if tokens >= token_budget:
            card = Scorecard(
                status=LoopStatus.budget,
                iterations=index,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=False,
                remaining_failures=remaining,
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        ctx = ast_context.build(result, project_root=root)

        try:
            plan, used = client_mod.request_fix_plan(
                oa_client, ctx, model=model, mock=use_mock, agentic=agentic
            )
        except Exception as exc:
            history.append(
                IterationRecord(
                    index=index,
                    status_before="fail",
                    tokens_used=0,
                    applied=False,
                    fix_plan=None,
                    error=str(exc),
                )
            )
            card = Scorecard(
                status=LoopStatus.error,
                iterations=index,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=False,
                remaining_failures=remaining + [str(exc)],
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        tokens += used

        if dry_run:
            history.append(
                IterationRecord(
                    index=index,
                    status_before="fail",
                    tokens_used=used,
                    applied=False,
                    fix_plan=plan,
                    error=None,
                )
            )
            card = Scorecard(
                status=LoopStatus.dry_run,
                iterations=index + 1,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=False,
                remaining_failures=remaining,
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        try:
            apply_mod.apply_fix_plan(plan, project_root=root, dry_run=False)
            history.append(
                IterationRecord(
                    index=index,
                    status_before="fail",
                    tokens_used=used,
                    applied=True,
                    fix_plan=plan,
                    error=None,
                )
            )
        except Exception as exc:
            history.append(
                IterationRecord(
                    index=index,
                    status_before="fail",
                    tokens_used=used,
                    applied=False,
                    fix_plan=plan,
                    error=str(exc),
                )
            )
            card = Scorecard(
                status=LoopStatus.error,
                iterations=index + 1,
                max_iterations=max_iter,
                tokens_used=tokens,
                token_budget=token_budget,
                passed=False,
                remaining_failures=remaining + [str(exc)],
                history=history,
                model="mock" if use_mock else model,
                fixture_or_target=fixture_label,
            )
            if write_report:
                report_mod.write_scorecard(card, project_root=root)
            return card

        index += 1
