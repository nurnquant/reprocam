"""steps.json + element map + bug claim (+ judge feedback) -> test_repro.py (pytest + Playwright).

Muse Spark Open (LLM_PROVIDER, EFFORT_TESTGEN) with structured output {test_code, notes}.
The model writes only the test body; PREAMBLE (imports, APP_URL, FIXED and the url() helper)
is ours and is prepended, so URLs are always built with urllib.parse and carry fixed=FIXED.

lint() catches what the runner should never execute: syntax errors, imports beyond the
standard library/pytest/playwright, a page.goto that doesn't go through url(), a URL whose
parsed query doesn't hold exactly one fixed=FIXED (or has a '?' inside a value), redefining
the preamble's names, and expect() messages that read the element (stale values).
"""
import ast
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from backend import dom_snapshot
from backend.llm import chat

PROMPTS = Path(__file__).resolve().parent / "prompts"


def prompt_version() -> str:
    """Prompt file in use: prompts/testgen_<version>.md, chosen by TESTGEN_PROMPT (default: newest)."""
    found = sorted(p.stem.removeprefix("testgen_") for p in PROMPTS.glob("testgen_v*.md"))
    return os.getenv("TESTGEN_PROMPT") or max(found, key=lambda v: int(v[1:]))
SCHEMA = {"type": "json_schema", "json_schema": {"name": "test", "strict": True, "schema": {
    "type": "object",
    "properties": {"test_code": {"type": "string"}, "notes": {"type": "string"}},
    "required": ["test_code", "notes"],
    "additionalProperties": False,
}}}
READS = {"inner_text", "text_content", "input_value", "get_attribute", "inner_html", "all_inner_texts",
         "all_text_contents"}
ALLOWED_IMPORTS = {"os", "re", "math", "decimal", "json", "time", "urllib", "pytest", "playwright"}
RESERVED = {"APP_URL", "FIXED", "url"}

PREAMBLE = '''import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Page, expect

APP_URL = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")
FIXED = os.environ.get("REPRO_FIXED", "0")


def url(path, **params):
    """APP_URL + path, with query params merged in. The build flag fixed=FIXED is always set."""
    parts = urlsplit(f"{APP_URL}/{path.lstrip('/')}")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    query["fixed"] = FIXED
    return urlunsplit(parts._replace(query=urlencode(query)))
'''


def check_goto_url(u: str, fixed: str) -> str | None:
    """None if the URL's parsed query holds exactly one fixed=<fixed> and no value contains '?'
    (a sign of a query string written by hand, like product.html?id=x?fixed=0)."""
    pairs = parse_qsl(urlsplit(u).query, keep_blank_values=True)
    flags = [v for k, v in pairs if k == "fixed"]
    if flags != [fixed]:
        return f"URL must carry exactly one fixed={fixed}, found {flags or 'none'}: {u}"
    bad = [f"{k}={v}" for k, v in pairs if "?" in k or "?" in v]
    if bad:
        return f"query value contains '?' (query string built by hand?): {bad[0]} in {u}"
    return None


def _url_helper():
    """The preamble's url(), bound to a test APP_URL and FIXED='0', for static checks."""
    scope = {"__name__": "preamble_check"}
    exec(PREAMBLE.replace('os.environ.get("APP_URL", "http://localhost:5173")', '"http://app"')
         .replace('os.environ.get("REPRO_FIXED", "0")', '"0"'), scope)
    return scope["url"]


def assemble(body: str) -> str:
    return PREAMBLE + "\n\n" + body.strip() + "\n"


def lint(code: str) -> str | None:
    """None if the (assembled) test may run, else a short reason (fed back to the generator)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno})"
    preamble_lines = PREAMBLE.count("\n")
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        bad = [n for n in names if n.split(".")[0] not in ALLOWED_IMPORTS]
        if bad:
            return f"import not allowed: {', '.join(bad)}"
    for node in tree.body:  # the body must not redefine the preamble's names
        if getattr(node, "lineno", 0) <= preamble_lines:
            continue
        targets = [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else \
            [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        if RESERVED & set(targets):
            return f"line {node.lineno}: don't redefine {', '.join(RESERVED & set(targets))}; the preamble provides it"

    url_helper, gotos = _url_helper(), 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_expect = getattr(node.func, "id", None) == "expect"
        if is_expect and len(node.args) + len(node.keywords) > 1:
            msg = node.args[1] if len(node.args) > 1 else node.keywords[0].value
            reads = [c.func.attr for c in ast.walk(msg)
                     if isinstance(c, ast.Call) and getattr(c.func, "attr", None) in READS]
            if reads:
                return (f"line {node.lineno}: expect() message calls {reads[0]}(); it runs before the assertion "
                        "waits and can show a stale value. Use a fixed message string.")
        if getattr(node.func, "attr", None) == "goto":
            gotos += 1
            target = node.args[0] if node.args else None
            if not (isinstance(target, ast.Call) and getattr(target.func, "id", None) == "url"):
                return (f"line {node.lineno}: page.goto must use url(path, **params), e.g. "
                        "page.goto(url(\"product.html\", id=\"x\")); never write query strings by hand")
            consts = all(isinstance(a, ast.Constant) for a in target.args) and \
                all(isinstance(k.value, ast.Constant) and k.arg for k in target.keywords)
            if consts and target.args:
                built = url_helper(*[a.value for a in target.args], **{k.arg: k.value.value for k in target.keywords})
                problem = check_goto_url(built, "0")
                if problem:
                    return f"line {node.lineno}: {problem}. Pass query values as url() keyword arguments."
    if not gotos:
        return "no page.goto(url(...)) call"
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in tree.body):
        return "no test function"
    return None


def generate(steps: dict, previous: list[dict] | None = None, effort: str | None = None,
             provider: str | None = None) -> tuple[str, str, dict]:
    """previous: earlier attempts [{test_code, outcome, failure, feedback}]. Returns (full file, notes, meta)."""
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
    version = prompt_version()
    system = (PROMPTS / f"testgen_{version}.md").read_text().replace("{PREAMBLE}", PREAMBLE.strip())
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]
    text, meta = chat(messages, stage="testgen", effort=effort, provider=provider, response_format=SCHEMA,
                      log_extra={"prompt_version": f"testgen {version}"})
    meta["prompt_version"] = f"testgen {version}"
    out = json.loads(text)
    body = out["test_code"].replace(PREAMBLE.strip(), "")  # in case the model repeated it anyway
    return assemble(body), out["notes"], meta


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.testgen runs/<name>")
    code, notes, meta = generate(json.loads((Path(sys.argv[1]) / "steps.json").read_text()))
    print(code)
    print("#", notes)
    print("# lint:", lint(code) or "ok", "| cost", meta["cost_usd"])
