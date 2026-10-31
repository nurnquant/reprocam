"""steps.json + element map + bug claim (+ judge feedback) -> test_repro.py (pytest + Playwright).

Muse Spark Open (LLM_PROVIDER, EFFORT_TESTGEN) with structured output {test_code, notes}.
lint() catches what the runner should never execute: syntax errors, a goto without the
explicit ?fixed={FIXED} build flag, or imports beyond the standard library/pytest/playwright.
"""
import ast
import json
import re
import sys
from pathlib import Path

from backend import dom_snapshot
from backend.llm import chat

PROMPT = Path(__file__).resolve().parent / "prompts" / "testgen.md"
SCHEMA = {"type": "json_schema", "json_schema": {"name": "test", "strict": True, "schema": {
    "type": "object",
    "properties": {"test_code": {"type": "string"}, "notes": {"type": "string"}},
    "required": ["test_code", "notes"],
    "additionalProperties": False,
}}}
READS = {"inner_text", "text_content", "input_value", "get_attribute", "inner_html", "all_inner_texts",
         "all_text_contents"}
ALLOWED_IMPORTS = {"os", "re", "math", "decimal", "json", "time", "pytest", "playwright"}


def lint(code: str) -> str | None:
    """None if the test may run, else a short reason (fed back to the generator)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno})"
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        bad = [n for n in names if n.split(".")[0] not in ALLOWED_IMPORTS]
        if bad:
            return f"import not allowed: {', '.join(bad)}"
    for node in ast.walk(tree):
        is_expect = isinstance(node, ast.Call) and getattr(node.func, "id", None) == "expect"
        if is_expect and len(node.args) + len(node.keywords) > 1:
            msg = node.args[1] if len(node.args) > 1 else node.keywords[0].value
            reads = [c.func.attr for c in ast.walk(msg)
                     if isinstance(c, ast.Call) and getattr(c.func, "attr", None) in READS]
            if reads:
                return (f"line {node.lineno}: expect() message calls {reads[0]}(); it runs before the assertion "
                        "waits and can show a stale value. Use a fixed message string.")
    gotos = re.findall(r"page\.goto\((.*?)\)\s*$", code, flags=re.M)
    if not gotos:
        return "no page.goto(...) call"
    for g in gotos:
        if "fixed={FIXED}" not in g:
            return f"page.goto must pass ?fixed={{FIXED}} explicitly: page.goto({g})"
    if not re.search(r"def test_\w+\(", code):
        return "no test function"
    return None


def generate(steps: dict, previous: list[dict] | None = None, effort: str | None = None,
             provider: str | None = None) -> tuple[str, str, dict]:
    """previous: earlier attempts [{test_code, outcome, failure, feedback}]. Returns (code, notes, meta)."""
    rows = dom_snapshot.load_or_build()
    parts = [
        "Steps the tester took:\n" + json.dumps(steps["steps"], indent=1),
        "Bug claim:\n" + json.dumps(steps["bug_claim"], indent=1),
        "Element map:\n" + dom_snapshot.to_prompt(rows),
    ]
    for i, p in enumerate(previous or [], 1):
        parts.append(f"Previous attempt {i}:\n```python\n{p['test_code']}\n```\n"
                     f"Result: {p['outcome']}\n{p['failure'][:1500]}\n"
                     f"Feedback: {p['feedback']}")
    messages = [{"role": "system", "content": PROMPT.read_text()},
                {"role": "user", "content": "\n\n".join(parts)}]
    text, meta = chat(messages, stage="testgen", effort=effort, provider=provider, response_format=SCHEMA)
    out = json.loads(text)
    return out["test_code"].strip() + "\n", out["notes"], meta


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.testgen runs/<name>")
    code, notes, meta = generate(json.loads((Path(sys.argv[1]) / "steps.json").read_text()))
    print(code)
    print("#", notes)
    print("# lint:", lint(code) or "ok", "| cost", meta["cost_usd"])
