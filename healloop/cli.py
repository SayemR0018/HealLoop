from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from healloop import __version__
from healloop.loop import run_loop
from healloop.report import load_scorecard, write_html
from healloop.schemas import LoopStatus

app = typer.Typer(
    name="healloop",
    help="Closed-loop pytest healer (GPT-6).",
    no_args_is_help=True,
    add_completion=False,
)


def _default_max_iter() -> int:
    return int(os.environ.get("HEALLOOP_MAX_ITER", "5"))


def _default_budget() -> int:
    return int(os.environ.get("HEALLOOP_TOKEN_BUDGET", "50000"))


def _exit_for(status: LoopStatus) -> int:
    if status in (LoopStatus.green, LoopStatus.dry_run):
        return 0
    if status == LoopStatus.error:
        return 2
    return 1


@app.command("run")
def run_cmd(
    target: str = typer.Argument(..., help="Path or pytest node to heal"),
    max_iter: int = typer.Option(_default_max_iter(), "--max-iter", help="Max repair iterations"),
    token_budget: int = typer.Option(
        _default_budget(), "--token-budget", help="Token budget across iterations"
    ),
    root: Path = typer.Option(Path("."), "--root", help="Project root"),
    mock: bool = typer.Option(False, "--mock", help="Use MockLLM (no API)"),
) -> None:
    """Full closed loop; write `.healloop/last_scorecard.json`."""
    try:
        # Env HEALLOOP_MOCK=1 also enables mock
        env_mock = os.environ.get("HEALLOOP_MOCK", "0") == "1"
        card = run_loop(
            target,
            project_root=root,
            max_iter=max_iter,
            token_budget=token_budget,
            mock=mock or env_mock,
            dry_run=False,
        )
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"hard error: {exc}", fg=typer.colors.RED, err=True)
        raise SystemExit(2) from exc

    typer.echo(card.model_dump_json(indent=2))
    raise SystemExit(_exit_for(card.status))


@app.command("dry-run")
def dry_run_cmd(
    target: str = typer.Argument(..., help="Path or pytest node"),
    max_iter: int = typer.Option(_default_max_iter(), "--max-iter"),
    token_budget: int = typer.Option(_default_budget(), "--token-budget"),
    root: Path = typer.Option(Path("."), "--root"),
    mock: bool = typer.Option(False, "--mock"),
) -> None:
    """Produce FixPlan only; status=dry_run (no file writes except scorecard)."""
    try:
        env_mock = os.environ.get("HEALLOOP_MOCK", "0") == "1"
        card = run_loop(
            target,
            project_root=root,
            max_iter=max_iter,
            token_budget=token_budget,
            mock=mock or env_mock,
            dry_run=True,
        )
    except Exception as exc:
        typer.secho(f"hard error: {exc}", fg=typer.colors.RED, err=True)
        raise SystemExit(2) from exc

    typer.echo(card.model_dump_json(indent=2))
    raise SystemExit(_exit_for(card.status))


@app.command("report")
def report_cmd(
    json_only: bool = typer.Option(False, "--json-only", help="Print JSON only"),
    html: bool = typer.Option(False, "--html", help="Also write/print HTML path"),
    root: Path = typer.Option(Path("."), "--root", help="Project root containing .healloop/"),
) -> None:
    """Print last scorecard; optional HTML."""
    try:
        card = load_scorecard(root)
    except FileNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise SystemExit(2) from exc
    except Exception as exc:
        typer.secho(f"hard error: {exc}", fg=typer.colors.RED, err=True)
        raise SystemExit(2) from exc

    typer.echo(card.model_dump_json(indent=2))
    if html:
        path = write_html(card, project_root=root)
        if not json_only:
            typer.echo(f"HTML: {path}")
    raise SystemExit(0)


@app.callback()
def _version_callback(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit", is_eager=True
    ),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)


def main() -> int:
    """Console script entry — Typer app is callable."""
    try:
        app()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
