# HealLoop — Atomic Task Checklist (The Core Builder)

**Spec:** `/workspace/astra-project/ARCH_SPEC.md` (authoritative)  
**Root:** `/workspace/astra-project/`  
**Model rule:** GPT-6 only via OpenAI API or Codex SDK. Mock path for tests.

## Quality gates (fail the task if violated)

- No `# TODO` / `# FIXME` / ellipsis stubs  
- No bare `pass` in production code  
- No silent exception swallowing  
- Type hints on all public functions/methods  
- No writes outside project root sandbox  

---

## Task 1 — Environment & dependency scaffolding

- [ ] Create full package tree per ARCH_SPEC §2  
- [ ] `pyproject.toml` with deps + console script `healloop`  
- [ ] `.gitignore`, `.env.example`, `README.md` stub (judge one-liner placeholder OK only in README until Task 4)  
- [ ] `pip install -e ".[dev]"` or `pip install -e .` succeeds  
- [ ] `python -m healloop --help` shows `run` / `dry-run` / `report`  

**Exit:** help works; tree matches spec.

## Task 2 — Schema & client initialisation

- [ ] `healloop/schemas.py` — FixPlan, FilePatch, FailureContext, Scorecard, enums (exact fields per ARCH_SPEC §4)  
- [ ] `healloop/client.py` — `build_client()`, `request_fix_plan()` using `gpt-6` + structured parse / tool fallback  
- [ ] MockLLM path when `HEALLOOP_MOCK=1` or `--mock`  
- [ ] `tests/test_schemas.py` covers validation (path traversal rejected, empty files rejected)  

**Exit:** schema tests green; mock client returns valid FixPlan for known fixture.

## Task 3 — Core logic & execution sandbox

- [ ] `runner.py` — pytest subprocess, capture failures  
- [ ] `ast_context.py` — traceback → FileSlice via AST  
- [ ] `apply.py` — unified diff apply + `is_relative_to` sandbox  
- [ ] `loop.py` — closed loop with max-iter + token budget  
- [ ] `report.py` — write `.healloop/last_scorecard.json` (+ optional HTML)  
- [ ] `cli.py` — wire commands and exit codes  

**Exit:** unit tests for apply + ast_context + loop_mock green.

## Task 4 — Local test run & error interception

- [ ] `examples/broken/` intentional failing fixture  
- [ ] `scripts/selftest_mock.sh` exits 0 on green scorecard  
- [ ] `HEALLOOP_MOCK=1 python -m healloop run examples/broken` → status green  
- [ ] CLI errors surface clearly (missing key when not mock → exit 2)  
- [ ] Quality-gate sweep: ripgrep for TODO/FIXME/bare pass  

**Exit:** mock selftest green; live GPT-6 optional smoke only if key present.

## Task 5 — Git initialisation & remote GitHub sync

- [ ] `git init` in `/workspace/astra-project` (if not already)  
- [ ] Initial commit with complete HealLoop tree  
- [ ] Create/link GitHub remote and push (`gh` or git remote)  
- [ ] README finalised with judge one-liner + env docs  

**Exit:** remote URL + commit SHA reported to Sprint Architect.

---

## Handback template (reply to Sprint Architect)

```text
HealLoop Task N status: done|blocked
Files: …
Mock selftest: pass|fail (paste scorecard status)
Live GPT-6: skipped|pass|fail
Git remote: …
Blockers: …
```
