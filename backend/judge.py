"""Did the generated test fail for the reason the tester described?

Rule layer first (BUILD_PLAN v2.1):
  pass        -> NOT_REPRODUCED  (decided_by rule)
  error       -> TEST_ERROR      (decided_by rule): selector/action timeouts, syntax, lint
  assert_fail -> model judge     (decided_by model): includes expect() timeouts
"""
import json
from pathlib import Path

from backend.llm import chat

PROMPT = Path(__file__).resolve().parent / "prompts" / "judge.md"
SCHEMA = {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["REPRODUCED", "NOT_REPRODUCED"]},
        "reason": {"type": "string"},
        "feedback_for_generator": {"type": "string"},
    },
    "required": ["verdict", "reason", "feedback_for_generator"],
    "additionalProperties": False,
}}}


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

    user = (f"Bug claim:\n{json.dumps(bug_claim, indent=1)}\n\n"
            f"Test code:\n```python\n{test_code}\n```\n\n"
            f"Failure ({result['exc_type']}):\n{result['message'][:2500]}")
    text, meta = chat([{"role": "system", "content": PROMPT.read_text()}, {"role": "user", "content": user}],
                      stage="judge", effort=effort, provider=provider, response_format=SCHEMA)
    return {**json.loads(text), "decided_by": "model"}, meta
