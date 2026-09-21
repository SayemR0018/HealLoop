# HealLoop

**Closed-loop pytest healer powered by GPT-6 / Codex.**

Failing tests → GPT-6 structured `FixPlan` (or optional agentic tool loop) → sandboxed unified-diff apply → re-run until green or budget. Emits a JSON `Scorecard` judges can inspect.

Built for the [Astra Commons: Dhaka](https://x.com/mitul_shahriyar/status/2101301348415549914) OpenAI API Credit Giveaway — developer infrastructure, not a prompt wrapper.

## Why HealLoop

| Capability | Detail |
|------------|--------|
| GPT-6 only | Hard-gated `HEALLOOP_MODEL=gpt-6` via OpenAI API (optional Codex path) |
| Structured outputs | Pydantic `FixPlan` / `Scorecard` via `beta.chat.completions.parse` |
| Agentic tools | Optional `HEALLOOP_AGENTIC=1`: `run_pytest`, `read_slice`, `submit_fix_plan` |
| Closed loop | Fail → plan → apply → re-test until green / max-iter / token budget |
| Mock-first | `HEALLOOP_MOCK=1` runs end-to-end with zero API spend |

```text
pytest fail ──► AST context ──► GPT-6 FixPlan ──► apply diff ──► re-run
                     ▲                                         │
                     └──────────── still failing? ◄────────────┘
                                      │
                                   Scorecard JSON
```

## Quickstart

```bash
git clone https://github.com/SayemR0018/HealLoop.git
cd HealLoop
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Mock demo (no API key) — expect Scorecard status "green"
HEALLOOP_MOCK=1 python -m healloop run examples/broken
```

### Demo output (mock)

```json
{
  "status": "green",
  "iterations": 1,
  "tokens_used": 100,
  "model": "mock",
  "fixture_or_target": "examples/broken",
  "passed": true
}
```

The intentional bug in `examples/broken/buggy_math.py` (`return a - b`) is patched to `return a + b` and tests pass.

## Live demo

Visit the mock-only shell: [https://YOUR-PROJECT.vercel.app](https://YOUR-PROJECT.vercel.app)

The page is a visit-and-try shell. One button runs the same closed loop as the CLI against a temp copy of `examples/broken` and prints the Scorecard. The Python CLI stays the product. The Vercel deployment is mock-only: the function forces `HEALLOOP_MOCK=1` and does not call a live model.

On Vercel, only set `HEALLOOP_MOCK=1`. Do not set `OPENAI_API_KEY`.

Manual project settings:

| Setting | Value |
|---------|--------|
| Framework preset | Other |
| Root directory | `.` |
| Build command | empty |
| Environment variable | Only set `HEALLOOP_MOCK=1` (Production, Preview, and Development) |

Deploy from the repo root:

```bash
vercel
vercel --prod
```

## Live GPT-6

```bash
cp .env.example .env   # set OPENAI_API_KEY
# HEALLOOP_MODEL=gpt-6  (default; other models are rejected)

python -m healloop run examples/broken
# Optional multi-tool agentic loop:
HEALLOOP_AGENTIC=1 python -m healloop run PATH/TO/FAILING/TESTS
```

## CLI

```bash
python -m healloop run TARGET [--max-iter 5] [--token-budget 50000] [--mock]
python -m healloop dry-run TARGET
python -m healloop report [--json-only] [--html]
```

Exit codes: `0` green / dry-run ok · `1` still failing / budget · `2` hard error.

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENAI_API_KEY` | — | Required unless mock |
| `HEALLOOP_MODEL` | `gpt-6` | **GPT-6 only** |
| `HEALLOOP_MAX_ITER` | `5` | Max repair iterations |
| `HEALLOOP_TOKEN_BUDGET` | `50000` | Token budget |
| `HEALLOOP_MOCK` | `0` | `1` = MockLLM, no network |
| `HEALLOOP_AGENTIC` | `0` | `1` = GPT-6 tool-calling loop |
| `HEALLOOP_USE_CODEX` | `0` | Optional Codex SDK (still gpt-6) |

## Tests

```bash
./scripts/selftest_mock.sh
python -m pytest tests/ -q
```

## License

MIT (see repository for details).
