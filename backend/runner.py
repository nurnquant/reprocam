"""Run a generated test in its own pytest subprocess and classify how it ended.

Generated code only ever executes here: a separate process, its own directory, a 60 s timeout.
A small pytest plugin (written next to the test) records the exception type of the first
failure, which is what the judge's rules need:

  pass         the test passed
  assert_fail  AssertionError in the test body; includes expect() timeouts, since Playwright's
               expect raises AssertionError
  error        anything else: syntax/import/collection errors, fixture errors, action timeouts
               (playwright TimeoutError from page.click etc.), selector errors, the 60 s limit
"""
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from backend.testgen import check_goto_url

TIMEOUT_S = 60
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


def run_test(code: str, workdir: str | Path, app_url: str, fixed: bool) -> dict:
    """Write and run test_repro.py in workdir. Returns outcome, exc_type, message, output, screenshot."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "test_repro.py").write_text(code)
    (workdir / "conftest.py").write_text(PLUGIN)
    (workdir / "pytest.ini").write_text("[pytest]\n")  # keep the repo's pytest.ini out of it
    (workdir / "result.json").unlink(missing_ok=True)

    env = {**os.environ, "APP_URL": app_url, "REPRO_FIXED": "1" if fixed else "0"}
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-p", "no:warnings", "--tb=short",
             "--screenshot", "on", "--output", "artifacts", "test_repro.py"],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
        output = proc.stdout + proc.stderr
        result = json.loads((workdir / "result.json").read_text()) if (workdir / "result.json").exists() \
            else {"outcome": "error", "phase": "session", "exc_type": None, "message": output[-3000:]}
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        result = {"outcome": "error", "phase": "timeout", "exc_type": "subprocess.TimeoutExpired",
                  "message": f"test did not finish within {TIMEOUT_S}s"}

    shots = sorted((workdir / "artifacts").rglob("*.png"))
    result["message"] = _scrub(result.get("message") or "")
    return {**result, "fixed": fixed, "seconds": round(time.time() - started, 1),
            "output": _scrub(output[-3000:]), "screenshot": str(shots[-1]) if shots else None}
