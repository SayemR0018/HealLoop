# HealLoop — Architecture Specification

**Project lead:** Sprint Architect  
**Implementer:** The Core Builder (Codex Builder)  
**Validator:** The Auditor & Social Publisher  
**Workspace root:** `/workspace/astra-project/`  
**Status:** execution-ready blueprint (no product implementation in this file)

---

## 1. Product one-liner

Closed-loop pytest healer: failing tests → GPT-6 structured `FixPlan` → apply unified diffs → re-run until green or budget hit. Emits a JSON `Scorecard` (optional HTML report).

## 2. Confirmed file tree

```text
/workspace/astra-project/
├── ARCH_SPEC.md                 # this document (source of truth)
├── ATOMIC_TASKS.md              # checklist for Core Builder
├── README.md                    # judge one-liner + demo (Task 1 stub → Task 5 polish)
├── pyproject.toml               # package + console script `healloop`
├── .env.example                 # OPENAI_API_KEY, HEALLOOP_MODEL, budgets
├── .gitignore
├── healloop/
│   ├── __init__.py              # __version__
│   ├── __main__.py              # python -m healloop
│   ├── cli.py                   # typer: run | dry-run | report
│   ├── schemas.py               # Pydantic FixPlan, FailureContext, Scorecard, …
│   ├── client.py                # OpenAI / Codex SDK init + structured FixPlan call
│   ├── runner.py                # pytest invocation + failure capture
│   ├── ast_context.py           # traceback → AST slices
│   ├── apply.py                 # unified-diff apply + path sandbox
│   ├── loop.py                  # closed loop orchestrator
│   └── report.py                # scorecard JSON + optional HTML
├── examples/
│   └── broken/
│       ├── buggy_math.py        # intentional bug
│       └── test_buggy_math.py   # failing pytest (HealLoop must green)
├── tests/
│   ├── test_schemas.py
│   ├── test_apply.py
│   ├── test_ast_context.py
│   ├── test_runner.py
│   └── test_loop_mock.py         # loop with MockLLM (no API credits)
├── scripts/
│   └── selftest_mock.sh         # one-shot mock harness
└── .healloop/                   # runtime artefacts (gitignored)
    ├── last_scorecard.json
    └── last_report.html
```

**Out of tree for v1:** HTTP API (`POST /jobs`). Only if Tasks 1–4 are green and time remains.

---

## 3. Quality gates (non-negotiable)

Core Builder **must not** ship:

| Forbidden | Required instead |
|-----------|------------------|
| `# TODO`, `# FIXME`, `# ...`, ellipsis stubs | Complete implementations |
| Bare `pass` in real functions (except abstract protocol bodies that raise) | Real logic or `raise NotImplementedError` only in tests of interfaces |
| Unhandled exceptions swallowed silently | Typed errors; catch at CLI boundary; non-zero exit |
| Missing type hints on public functions / methods | Full annotations + `from __future__ import annotations` |
| Any LLM except GPT-6 via OpenAI API or Codex SDK | `HEALLOOP_MODEL=gpt-6` (or Codex equivalent) |
| Writing outside the target project root | Path sandbox in `apply.py` |

PR / handoff is rejected if any gate fails.

---

## 4. Concrete I/O schema

### 4.1 Pydantic models (`healloop/schemas.py`)

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class FilePatch(BaseModel):
    path: str = Field(..., description="Repo-relative path under project root")
    unified_diff: str = Field(..., min_length=1)

    @field_validator("path")
    @classmethod
    def no_abs_or_dotdot(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("path must be relative and must not contain ..")
        return v


class FixPlan(BaseModel):
    """Structured model output — enforced via response_format / parse."""

    rationale: str
    risk: RiskLevel
    files: list[FilePatch] = Field(..., min_length=1)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class FailureRecord(BaseModel):
    nodeid: str
    traceback: str
    file: str | None = None
    line: int | None = None


class FileSlice(BaseModel):
    path: str
    start_line: int
    end_line: int
    source: str
    symbol: str | None = None


class FailureContext(BaseModel):
    project_root: str
    failures: list[FailureRecord]
    slices: list[FileSlice]
    pytest_stdout: str
    pytest_stderr: str
    exit_code: int


class LoopStatus(str, Enum):
    green = "green"
    budget = "budget"
    max_iter = "max_iter"
    error = "error"
    dry_run = "dry_run"


class IterationRecord(BaseModel):
    index: int
    status_before: Literal["fail", "pass"]
    tokens_used: int = 0
    applied: bool = False
    fix_plan: FixPlan | None = None
    error: str | None = None


class Scorecard(BaseModel):
    status: LoopStatus
    iterations: int
    max_iterations: int
    tokens_used: int
    token_budget: int
    passed: bool
    remaining_failures: list[str] = Field(default_factory=list)
    history: list[IterationRecord] = Field(default_factory=list)
    model: str
    fixture_or_target: str
```

### 4.2 CLI argument spec (`healloop/cli.py` via Typer)

| Command | Args / flags | Behaviour |
|---------|--------------|-----------|
| `healloop run` | `TARGET` (path or pytest node), `--max-iter INT=5`, `--token-budget INT=50000`, `--root PATH=.`, `--mock` | Full closed loop; write `.healloop/last_scorecard.json` |
| `healloop dry-run` | same as `run` without apply | Produce FixPlan only; `status=dry_run` |
| `healloop report` | `--json-only` / `--html` | Print last scorecard; optional HTML path |

Exit codes: `0` green or successful dry-run; `1` still failing / budget / max_iter; `2` usage or hard error.

### 4.3 JSON Scorecard example (success)

```json
{
  "status": "green",
  "iterations": 2,
  "max_iterations": 5,
  "tokens_used": 4120,
  "token_budget": 50000,
  "passed": true,
  "remaining_failures": [],
  "history": [],
  "model": "gpt-6",
  "fixture_or_target": "examples/broken"
}
```

---

## 5. OpenAI / Codex configuration (exact)

### 5.1 Environment

```bash
# .env.example
OPENAI_API_KEY=sk-...
HEALLOOP_MODEL=gpt-6
HEALLOOP_MAX_ITER=5
HEALLOOP_TOKEN_BUDGET=50000
HEALLOOP_MOCK=0
```

### 5.2 Client initialisation (`healloop/client.py`)

**Primary path — OpenAI Python SDK (Responses or Chat Completions with structured parse):**

```python
from __future__ import annotations

import os
from openai import OpenAI

from healloop.schemas import FailureContext, FixPlan

DEFAULT_MODEL = os.environ.get("HEALLOOP_MODEL", "gpt-6")


def build_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required unless HEALLOOP_MOCK=1")
    return OpenAI(api_key=api_key)


def request_fix_plan(client: OpenAI, context: FailureContext, *, model: str = DEFAULT_MODEL) -> tuple[FixPlan, int]:
    """Return (plan, total_tokens). Uses structured outputs → FixPlan."""
    system = (
        "You are HealLoop, a precise pytest repair agent. "
        "Return only a FixPlan: minimal unified diffs that fix the failing tests. "
        "Never modify files outside the provided slices' directories. "
        "Prefer the smallest correct change."
    )
    user = context.model_dump_json()

    # Preferred: chat.completions.parse with Pydantic (openai>=1.40 style)
    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=FixPlan,
        temperature=0.2,
    )
    plan = completion.choices[0].message.parsed
    if plan is None:
        raise RuntimeError("Model returned empty FixPlan")
    usage = getattr(completion, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    return plan, tokens
```

**Alternate path — Codex SDK** (if `HEALLOOP_USE_CODEX=1`):

- Initialise the official OpenAI Codex SDK client with the same `OPENAI_API_KEY`.
- Model id must remain **`gpt-6`** (or the Codex alias that maps to GPT-6).
- Tool / output contract: still produce a validated `FixPlan` (parse JSON → `FixPlan.model_validate`).
- Do **not** call Anthropic, Google, local GGUF, or any non-OpenAI endpoint.

### 5.3 Tool definition format (if using tool-calling instead of `parse`)

When structured `parse` is unavailable, register a single function tool:

```json
{
  "type": "function",
  "function": {
    "name": "submit_fix_plan",
    "description": "Submit a validated repair plan for failing pytest tests",
    "parameters": {
      "$ref": "#/components/schemas/FixPlan"
    }
  }
}
```

JSON Schema for tools **must** be generated from Pydantic:

```python
FixPlan.model_json_schema()
```

After `tool_calls[0].function.arguments`, run `FixPlan.model_validate_json(...)`.

### 5.4 Endpoints

| Mode | SDK method | Underlying API |
|------|------------|----------------|
| Default | `client.beta.chat.completions.parse` | `POST https://api.openai.com/v1/chat/completions` |
| Fallback | `client.chat.completions.create` + tool | same |
| Codex path | Codex SDK completion/turn API | OpenAI Codex endpoints only |

Base URL override only via `OPENAI_BASE_URL` if the org requires it; default official OpenAI.

---

## 6. Core control flow

```text
healloop run TARGET
    │
    ├─ resolve project_root + target
    ├─ loop index = 0, tokens = 0
    │
    └─ while True:
           result = runner.run_pytest(TARGET)
           if result.ok → Scorecard(status=green); break
           if index >= max_iter → Scorecard(status=max_iter); break
           if tokens >= budget → Scorecard(status=budget); break
           ctx = ast_context.build(result)
           if mock: plan = MockLLM.next_plan(ctx)
           else: plan, used = client.request_fix_plan(ctx); tokens += used
           if dry_run → Scorecard(status=dry_run, fix_plan=plan); break
           apply.apply_fix_plan(plan, root=project_root)
           index += 1
```

### 6.1 Path sandbox (`apply.py`)

- Resolve each `FilePatch.path` against `project_root`.
- Reject if resolved path is outside `project_root` (`Path.resolve().is_relative_to`).
- Apply with `unidiff` or stdlib+manual hunks; on failure record error and abort iteration (do not leave partial writes — apply all-or-nothing per plan when possible).

### 6.2 AST context (`ast_context.py`)

- Parse pytest traceback for `File "…", line N`.
- Open file; `ast.parse`; find enclosing `FunctionDef`/`AsyncFunctionDef`/`ClassDef`.
- Emit `FileSlice` with ± small margin (default 2 lines) capped at 200 lines per slice.
- Cap total context characters (e.g. 24_000) — truncate lowest-priority slices first.

---

## 7. Mock data / self-test harness (no API credits)

### 7.1 MockLLM (`healloop/client.py` or `healloop/mock_llm.py`)

When `HEALLOOP_MOCK=1` or `--mock`:

1. Detect known fixture fingerprint: `examples/broken/buggy_math.py` contains `return a - b` while tests expect addition.
2. Return a canned `FixPlan` that replaces `-` with `+` via a correct unified diff.
3. Token accounting: charge a fixed fake `tokens_used=100` per call so budget logic is exercised in `tests/test_loop_mock.py`.

### 7.2 Intentional failing fixture

`examples/broken/buggy_math.py`:

```python
def add(a: int, b: int) -> int:
    return a - b  # intentional bug — HealLoop must change to a + b
```

`examples/broken/test_buggy_math.py`:

```python
from buggy_math import add

def test_add_positive() -> None:
    assert add(2, 3) == 5
```

### 7.3 Self-test commands

```bash
# Unit tests without network
cd /workspace/astra-project
python -m pytest tests/ -q

# Full closed loop on fixture with MockLLM (zero OpenAI spend)
HEALLOOP_MOCK=1 python -m healloop run examples/broken --max-iter 3 --token-budget 5000

# Expect: scorecard status=green, examples/broken/buggy_math.py fixed to a + b

# Optional live smoke (credits): only after mock is green
HEALLOOP_MOCK=0 HEALLOOP_MODEL=gpt-6 python -m healloop run examples/broken --max-iter 3
```

`scripts/selftest_mock.sh` must wrap the mock run and `grep` for `"status": "green"` (or parse JSON with Python) and exit non-zero on failure.

---

## 8. Dependencies (`pyproject.toml` sketch)

```toml
[project]
name = "healloop"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "openai>=1.40.0",
  "pydantic>=2.7",
  "typer>=0.12",
  "pytest>=8.0",
  "unidiff>=0.7",
]

[project.scripts]
healloop = "healloop.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## 9. Atomic Task Checklist (for @Codex Builder / The Core Builder)

See also `ATOMIC_TASKS.md`. Summary:

| ID | Task | Done when |
|----|------|-----------|
| **Task 1** | Environment & dependency scaffolding | `pyproject.toml`, package layout, README stub, `.gitignore`, `.env.example`; `pip install -e .` works; `python -m healloop --help` works |
| **Task 2** | Schema & client initialisation | `schemas.py` complete; `client.py` with GPT-6 structured `FixPlan` + MockLLM path; unit tests for schema validation |
| **Task 3** | Core logic & execution sandbox | `runner.py`, `ast_context.py`, `apply.py`, `loop.py`, `report.py`, `cli.py`; path sandbox enforced |
| **Task 4** | Local test run & error interception | `examples/broken` fixture; `tests/*` green; `HEALLOOP_MOCK=1` loop greens fixture; CLI exit codes correct; no forbidden stubs |
| **Task 5** | Git init & remote GitHub sync | `git init`, initial commit, `gh repo create` / remote push per user credentials; public README one-liner ready for judges |

**Report back to Sprint Architect** with: files created, mock selftest transcript, whether live GPT-6 was attempted, blockers (esp. missing `OPENAI_API_KEY`).

---

## 10. Success criteria (Definition of Done)

1. Mock closed loop greens `examples/broken` without API calls.  
2. `FixPlan` always validated by Pydantic before apply.  
3. Loop stops on `green` | `max_iter` | `budget` | `error`.  
4. Scorecard JSON written and printed.  
5. README judge path: install + `HEALLOOP_MOCK=1 python -m healloop run examples/broken`.  
6. Quality gates clean (no TODOs / bare `pass` / missing hints / wrong model).

---

## 11. Explicit non-goals (v1)

- Multi-repo healing, CI marketplace UI, video demos.  
- Models other than GPT-6.  
- Writing large unrelated refactors in the target project.
