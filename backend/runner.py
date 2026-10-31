"""Run a generated test in isolation and classify how it ended.

Generated code never runs in this process. Locally it runs in a pytest subprocess with a minimal
environment (no API keys); with REPRO_SANDBOX=modal it runs in a Modal Sandbox with no network
except the practice store served inside the sandbox (backend/modal_sandbox.py). Both use
backend/sandbox_exec.py. A small pytest plugin (written next to the test) records the exception
type of the first failure, which is what the judge's rules need:

  pass         the test passed
  assert_fail  AssertionError in the test body; includes expect() timeouts, since Playwright's
               expect raises AssertionError
  error        anything else: syntax/import/collection errors, fixture errors, action timeouts
               (playwright TimeoutError from page.click etc.), selector errors, the 60 s limit
"""
import base64
import inspect
import json
import os
from pathlib import Path

from backend.sandbox_exec import execute
from backend.testgen import check_goto_url

TIMEOUT_S = 60
ACTION_TIMEOUT_MS = 10_000  # clicks/fills/navigation; expect() timeouts stay as the test writes them
REPO = str(Path(__file__).resolve().parent.parent)
HOME = str(Path.home())


def _scrub(text: str) -> str:
    """Logs end up in the public repo (judge_log.jsonl): never keep local paths."""
    return text.replace(REPO, "<repo>").replace(HOME, "~")

PLUGIN = '''
import json
import os
from urllib.parse import parse_qsl, urlsplit

import pytest


class GotoGuardError(Exception):
    """A page.goto URL without exactly one fixed=REPRO_FIXED (or with a hand-built query)."""


@pytest.fixture(autouse=True)
def _goto_guard(page):
    """Check every navigation at run time too: the build flag must be right or the run means nothing."""
    original, fixed = page.goto, os.environ.get("REPRO_FIXED", "0")
    # A missing element should fail fast as a test error, not wait Playwright's default 30 s.
    page.set_default_timeout(int(os.environ.get("REPRO_ACTION_TIMEOUT_MS", "10000")))

    def goto(url, *args, **kwargs):
        problem = check_goto_url(url, fixed)
        if problem:
            raise GotoGuardError(problem)
        return original(url, *args, **kwargs)

    page.goto = goto
    yield

RESULT = {"outcome": "error", "phase": None, "exc_type": None, "message": "no test ran"}
_done = False


def _record(outcome, phase, excinfo, longrepr):
    global _done
    if _done:
        return
    _done = outcome != "pass"
    et = excinfo.type if excinfo else None
    RESULT.update(outcome=outcome, phase=phase,
                  exc_type=f"{et.__module__}.{et.__qualname__}" if et else None,
                  message=(str(excinfo.value) if excinfo else str(longrepr or ""))[:3000])


def pytest_collectreport(report):
    if report.failed:
        _record("error", "collect", None, report.longrepr)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rep = (yield).get_result()
    if rep.failed:
        is_assert = rep.when == "call" and call.excinfo is not None and call.excinfo.errisinstance(AssertionError)
        _record("assert_fail" if is_assert else "error", rep.when, call.excinfo, rep.longrepr)
    elif rep.when == "call" and rep.passed:
        _record("pass", "call", None, None)


def pytest_sessionfinish(session):
    with open("result.json", "w") as f:
        json.dump(RESULT, f)

''' + inspect.getsource(check_goto_url)


def failure_summary(message: str | None) -> str:
    """First line of a failure plus Playwright's 'Expected value' / 'Actual value' lines."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    keep = [lines[0]] + [ln for ln in lines[1:4] if ln.startswith(("Expected", "Actual", "Received"))]
    return " | ".join(keep)


def run_test(code: str, workdir: str | Path, app_url: str, fixed: bool, query: str = "") -> dict:
    """Run test_repro.py (locally in workdir, or in a Modal Sandbox). Returns outcome, exc_type, message,
    output, seconds, and the final screenshot saved under workdir/artifacts/."""
    workdir = Path(workdir)
    if os.getenv("REPRO_SANDBOX") == "modal":
        from backend.modal_sandbox import run_in_sandbox  # needs the modal package and credentials

        result = run_in_sandbox(code, PLUGIN, fixed, ACTION_TIMEOUT_MS, TIMEOUT_S, query)
        png = result.pop("screenshot_png", None)
        result["screenshot"] = None
        if png:
            shot = workdir / "artifacts" / "final.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(base64.b64decode(png))
            result["screenshot"] = str(shot)
        (workdir / "test_repro.py").write_text(code)
        # same files as a local run, so run summaries (and the UI) read results the same way
        (workdir / "result.json").write_text(json.dumps({k: result.get(k) for k in ("outcome", "phase", "exc_type", "message")}))
    else:
        result = execute(code, PLUGIN, workdir, app_url, fixed, ACTION_TIMEOUT_MS, TIMEOUT_S, query)
    result["message"] = _scrub(result.get("message") or "")
    result["output"] = _scrub(result.get("output") or "")
    return result
