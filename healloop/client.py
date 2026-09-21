from __future__ import annotations

import json
import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from openai import OpenAI

from healloop.schemas import FailureContext, FilePatch, FixPlan, RiskLevel
from healloop.tools import TOOL_DEFINITIONS, execute_tool

DEFAULT_MODEL = os.environ.get("HEALLOOP_MODEL", "gpt-6")
MOCK_TOKENS = 100
AGENTIC_MAX_ROUNDS = 12


def build_client(*, mock: bool = False) -> OpenAI | None:
    """Return an OpenAI client, or None when mock mode is active.

    Raises RuntimeError if OPENAI_API_KEY is missing and mock is False.
    """
    use_mock = mock or os.environ.get("HEALLOOP_MOCK", "0") == "1"
    if use_mock:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required unless HEALLOOP_MOCK=1")
    base_url = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _unified_diff(path: str, old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    n_old = len(old_lines) or 1
    n_new = len(new_lines) or 1
    diff_lines: list[str] = [
        f"--- a/{path}\n",
        f"+++ b/{path}\n",
        f"@@ -1,{n_old} +1,{n_new} @@\n",
    ]
    sm = SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                diff_lines.append(" " + line)
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                diff_lines.append("-" + line)
            for line in new_lines[j1:j2]:
                diff_lines.append("+" + line)
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                diff_lines.append("-" + line)
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                diff_lines.append("+" + line)
    return "".join(diff_lines)


class MockLLM:
    """Deterministic healer for the examples/broken fixture (no network)."""

    @staticmethod
    def next_plan(context: FailureContext) -> tuple[FixPlan, int]:
        root = Path(context.project_root)
        candidates: list[Path] = []

        for sl in context.slices:
            p = Path(sl.path)
            candidates.append(p if p.is_absolute() else root / p)
        for fail in context.failures:
            if fail.file:
                p = Path(fail.file)
                candidates.append(p if p.is_absolute() else root / p)

        # Known fixture locations
        candidates.extend(
            [
                root / "buggy_math.py",
                root / "examples" / "broken" / "buggy_math.py",
            ]
        )

        target: Path | None = None
        old_text = ""
        for cand in candidates:
            if cand.is_file():
                text = cand.read_text(encoding="utf-8")
                if "return a - b" in text:
                    target = cand
                    old_text = text
                    break

        if target is None or "return a - b" not in old_text:
            raise RuntimeError(
                "MockLLM: unknown failure fingerprint; expected buggy_math return a - b"
            )

        try:
            rel = str(target.resolve().relative_to(root.resolve())).replace("\\", "/")
        except ValueError as exc:
            raise RuntimeError(f"MockLLM: file outside project root: {target}") from exc

        new_text = old_text.replace("return a - b", "return a + b", 1)
        unified = _unified_diff(rel, old_text, new_text)
        plan = FixPlan(
            rationale="Replace subtraction with addition in add() to match test expectation.",
            risk=RiskLevel.low,
            files=[FilePatch(path=rel, unified_diff=unified)],
            confidence=0.95,
        )
        return plan, MOCK_TOKENS


def _tool_fallback(
    client: OpenAI,
    *,
    model: str,
    system: str,
    user: str,
) -> tuple[FixPlan, int]:
    schema = FixPlan.model_json_schema()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "submit_fix_plan",
                "description": "Submit a validated repair plan for failing pytest tests",
                "parameters": schema,
            },
        }
    ]
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "submit_fix_plan"}},
        temperature=0.2,
    )
    choice = completion.choices[0]
    tool_calls = choice.message.tool_calls
    if not tool_calls:
        raise RuntimeError("Model returned no tool_calls for FixPlan fallback")
    args = tool_calls[0].function.arguments
    plan = FixPlan.model_validate_json(args)
    usage = getattr(completion, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    return plan, tokens


def _parse_tool_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _agentic_request_fix_plan(
    client: OpenAI,
    context: FailureContext,
    *,
    model: str,
) -> tuple[FixPlan, int]:
    """Multi-round tool-calling loop; must terminate with a validated FixPlan."""
    root = Path(context.project_root).resolve()
    system = (
        "You are HealLoop in agentic mode. Use the provided tools to inspect "
        "failures (read_slice, run_pytest) and finish by calling submit_fix_plan "
        "with a minimal FixPlan of unified diffs. Never escape the project root. "
        "Prefer the smallest correct change. Model policy: gpt-6 only."
    )
    user = (
        "Repair the failing pytest suite. FailureContext JSON follows.\n"
        + context.model_dump_json()
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    total_tokens = 0
    plan: FixPlan | None = None

    for _round in range(AGENTIC_MAX_ROUNDS):
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=0.2,
        )
        usage = getattr(completion, "usage", None)
        total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        choice = completion.choices[0]
        message = choice.message
        tool_calls = getattr(message, "tool_calls", None) or []

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }
        if tool_calls:
            serialized_calls: list[dict[str, Any]] = []
            for tc in tool_calls:
                serialized_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
            assistant_msg["tool_calls"] = serialized_calls
        messages.append(assistant_msg)

        if not tool_calls:
            # Model stopped without tools — try to parse content as FixPlan JSON
            content = (message.content or "").strip()
            if content:
                try:
                    plan = FixPlan.model_validate_json(content)
                    return plan, total_tokens
                except Exception:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Respond by calling submit_fix_plan with a "
                                "valid FixPlan; do not reply with free text."
                            ),
                        }
                    )
                    continue
            messages.append(
                {
                    "role": "user",
                    "content": "Call submit_fix_plan with a valid FixPlan now.",
                }
            )
            continue

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = _parse_tool_arguments(tc.function.arguments)
            except json.JSONDecodeError as exc:
                tool_result = json.dumps({"error": f"invalid JSON arguments: {exc}"})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
                continue

            if name == "submit_fix_plan":
                try:
                    plan = FixPlan.model_validate(args)
                    tool_payload = execute_tool(
                        name, args, project_root=root
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_payload,
                        }
                    )
                    return plan, total_tokens
                except Exception as exc:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(
                                {"error": f"FixPlan validation failed: {exc}"}
                            ),
                        }
                    )
                    plan = None
                    continue

            tool_payload = execute_tool(name, args, project_root=root)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_payload,
                }
            )

    if plan is not None:
        return plan, total_tokens
    raise RuntimeError(
        f"Agentic loop exhausted {AGENTIC_MAX_ROUNDS} rounds without FixPlan"
    )


def request_fix_plan(
    client: OpenAI | None,
    context: FailureContext,
    *,
    model: str = DEFAULT_MODEL,
    mock: bool = False,
    agentic: bool | None = None,
) -> tuple[FixPlan, int]:
    """Return (plan, total_tokens). Uses structured outputs → FixPlan.

    When *agentic* is True (or HEALLOOP_AGENTIC=1) and not mock, runs a
    multi-round GPT-6 tool-calling loop via TOOL_DEFINITIONS.
    """
    use_mock = mock or client is None or os.environ.get("HEALLOOP_MOCK", "0") == "1"
    if use_mock:
        return MockLLM.next_plan(context)

    if agentic is None:
        agentic = os.environ.get("HEALLOOP_AGENTIC", "0") == "1"

    if os.environ.get("HEALLOOP_USE_CODEX", "0") == "1":
        model = os.environ.get("HEALLOOP_MODEL", "gpt-6")

    if model != "gpt-6":
        raise RuntimeError(f"HealLoop only supports gpt-6, got model={model!r}")

    assert client is not None

    if agentic:
        return _agentic_request_fix_plan(client, context, model=model)

    system = (
        "You are HealLoop, a precise pytest repair agent. "
        "Return only a FixPlan: minimal unified diffs that fix the failing tests. "
        "Never modify files outside the provided slices' directories. "
        "Prefer the smallest correct change."
    )
    user = context.model_dump_json()

    try:
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
            return _tool_fallback(client, model=model, system=system, user=user)
        usage = getattr(completion, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        return plan, tokens
    except (AttributeError, TypeError) as exc:
        try:
            return _tool_fallback(client, model=model, system=system, user=user)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"structured parse and tool fallback both failed: {exc}; {fallback_exc}"
            ) from fallback_exc
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("parse", "response_format", "beta", "structured")):
            return _tool_fallback(client, model=model, system=system, user=user)
        raise
