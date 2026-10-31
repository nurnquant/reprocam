"""Did the generated test fail for the reason the tester described?

Rule layer first (BUILD_PLAN v2.1):
  pass        -> NOT_REPRODUCED  (decided_by rule)
  error       -> TEST_ERROR      (decided_by rule): selector/action timeouts, syntax, lint
  assert_fail -> values first: if the claim names specific amounts and the test observed a
                 different one, it is on the wrong state -> TEST_ERROR (decided_by rule);
                 otherwise the model judge (decided_by model), given both values side by side.
"""
import json
import re
from decimal import Decimal
from pathlib import Path

from backend.llm import chat

PROMPT = Path(__file__).resolve().parent / "prompts" / "judge.md"
SCHEMA = {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["REPRODUCED", "NOT_REPRODUCED", "TEST_ERROR"]},
        "reason": {"type": "string"},
        "feedback_for_generator": {"type": "string"},
    },
    "required": ["verdict", "reason", "feedback_for_generator"],
    "additionalProperties": False,
}}}


MONEY = re.compile(r"(-?)\$\s?(\d[\d,]*(?:\.\d+)?)")
WRONG_STATE = "Test isn't on the reported state (wrong product/page)."


def observed_actual(message: str | None) -> str | None:
    """Playwright's 'Actual value: ...' line from a failed expect(), if any."""
    m = re.search(r"^\s*Actual value:\s*(.*?)\s*$", message or "", re.M)
    return m.group(1) if m else None


def amounts(text: str | None) -> set[Decimal]:
    return {Decimal(sign + num.replace(",", "")) for sign, num in MONEY.findall(text or "")}


def wrong_state(claim: dict, observed: str | None) -> tuple[set, set] | None:
    """(claimed, seen) amounts when the test saw an amount the tester never reported, else None."""
    claimed = amounts(" ".join(str(claim.get(k, "")) for k in ("summary", "actual", "expected")))
    seen = amounts(observed)
    if claimed and seen and not (seen & claimed):
        return claimed, seen
    return None


def judge(bug_claim: dict, test_code: str, result: dict, effort: str | None = None,
          provider: str | None = None) -> tuple[dict, dict | None]:
    """Returns (verdict, model call meta or None when a rule decided)."""
    if result["outcome"] == "pass":
        return {"verdict": "NOT_REPRODUCED", "decided_by": "rule",
                "reason": "The test passed on the buggy build, so it never caught the bug.",
                "feedback_for_generator": "The test passed while the bug is present. Make sure it performs "
                "every step that triggers the bug (including repeated steps) and that the final assertion "
                "checks the claim's expected behaviour."}, None
    if result["outcome"] == "error":
        return {"verdict": "TEST_ERROR", "decided_by": "rule",
                "reason": f"{result['exc_type'] or 'error'} during {result['phase']}: {result['message'][:300]}",
                "feedback_for_generator": "The test broke before reaching its assertion. Fix this error: "
                f"{result['exc_type'] or ''} {result['message'][:800]}"}, None

    observed = observed_actual(result.get("message"))
    mismatch = wrong_state(bug_claim, observed)
    if mismatch:
        claimed, seen = (", ".join(f"${v:,.2f}".replace("$-", "-$") for v in sorted(x)) for x in mismatch)
        return {"verdict": "TEST_ERROR", "decided_by": "rule",
                "reason": f"The test observed {seen}, but the tester reported {claimed}.",
                "feedback_for_generator": f"{WRONG_STATE} The tester's screen showed {claimed}; your test saw "
                f"{seen}. Check which product, page and starting state the tester was on, and replay that."}, None

    user = (f"Bug claim:\n{json.dumps(bug_claim, indent=1)}\n\n"
            f"Test code:\n```python\n{test_code}\n```\n\n"
            f"Failure ({result['exc_type']}):\n{result['message'][:2500]}\n\n"
            f"Compare these two:\n- The tester saw (claim actual): {bug_claim.get('actual')}\n"
            f"- The test observed (Actual value): {observed or '(not reported; see the failure above)'}")
    text, meta = chat([{"role": "system", "content": PROMPT.read_text()}, {"role": "user", "content": user}],
                      stage="judge", effort=effort, provider=provider, response_format=SCHEMA)
    return {**json.loads(text), "decided_by": "model"}, meta
