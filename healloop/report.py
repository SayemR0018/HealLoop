from __future__ import annotations

import html
from pathlib import Path

from healloop.schemas import Scorecard

SCORECARD_NAME = "last_scorecard.json"
HTML_NAME = "last_report.html"


def healloop_dir(project_root: str | Path) -> Path:
    d = Path(project_root).resolve() / ".healloop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_scorecard(
    scorecard: Scorecard,
    *,
    project_root: str | Path,
    also_html: bool = False,
) -> Path:
    """Write `.healloop/last_scorecard.json` and optionally HTML."""
    out_dir = healloop_dir(project_root)
    json_path = out_dir / SCORECARD_NAME
    json_path.write_text(
        scorecard.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    if also_html:
        write_html(scorecard, project_root=project_root)
    return json_path


def write_html(
    scorecard: Scorecard,
    *,
    project_root: str | Path,
) -> Path:
    out_dir = healloop_dir(project_root)
    html_path = out_dir / HTML_NAME
    status = html.escape(scorecard.status.value)
    rows = ""
    for it in scorecard.history:
        err = html.escape(it.error or "")
        rows += (
            f"<tr><td>{it.index}</td><td>{it.status_before}</td>"
            f"<td>{it.tokens_used}</td><td>{it.applied}</td>"
            f"<td>{err}</td></tr>\n"
        )
    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>HealLoop Scorecard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
.status-green {{ color: #0a0; }}
.status-error, .status-budget, .status-max_iter {{ color: #c00; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
</style>
</head>
<body>
<h1>HealLoop Scorecard</h1>
<p>Status: <strong class="status-{status}">{status}</strong></p>
<ul>
<li>Iterations: {scorecard.iterations} / {scorecard.max_iterations}</li>
<li>Tokens: {scorecard.tokens_used} / {scorecard.token_budget}</li>
<li>Passed: {scorecard.passed}</li>
<li>Model: {html.escape(scorecard.model)}</li>
<li>Target: {html.escape(scorecard.fixture_or_target)}</li>
</ul>
<h2>Remaining failures</h2>
<ul>
{"".join(f"<li>{html.escape(f)}</li>" for f in scorecard.remaining_failures) or "<li>(none)</li>"}
</ul>
<h2>History</h2>
<table>
<thead><tr><th>#</th><th>before</th><th>tokens</th><th>applied</th><th>error</th></tr></thead>
<tbody>
{rows or "<tr><td colspan='5'>(empty)</td></tr>"}
</tbody>
</table>
</body>
</html>
"""
    html_path.write_text(body, encoding="utf-8")
    return html_path


def load_scorecard(project_root: str | Path) -> Scorecard:
    path = healloop_dir(project_root) / SCORECARD_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no scorecard at {path}")
    return Scorecard.model_validate_json(path.read_text(encoding="utf-8"))
