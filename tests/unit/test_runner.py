"""runner classification + judge rule layer, on tiny inline pages (no store, no model calls)."""
import pytest

from backend.judge import judge
from backend.runner import run_test
from backend.testgen import lint

HEADER = '''import os
from playwright.sync_api import Page, expect

FIXED = os.environ.get("REPRO_FIXED", "0")


def test_reproduces_bug(page: Page):
    page.set_content('<p data-testid="msg">hello</p><button data-testid="go" disabled>Go</button>')
'''

CASES = {
    "pass": ('    expect(page.get_by_test_id("msg")).to_have_text("hello")\n', "pass", None),
    "plain_assert": ('    assert 1 + 1 == 3, "math is broken"\n', "assert_fail", "AssertionError"),
    "expect_timeout": ('    expect(page.get_by_test_id("never"), "should appear").to_be_visible(timeout=500)\n',
                       "assert_fail", "AssertionError"),
    "action_timeout": ('    page.get_by_test_id("go").click(timeout=500)\n', "error", "TimeoutError"),
    "syntax": ('    expect(\n', "error", None),
}


@pytest.mark.parametrize("name", CASES)
def test_runner_classifies_outcome(name, tmp_path):
    body, outcome, exc = CASES[name]
    result = run_test(HEADER + body, tmp_path, "http://localhost:5173", fixed=False)
    assert result["outcome"] == outcome, result
    if exc:
        assert result["exc_type"].endswith(exc)


def test_runner_passes_build_flag(tmp_path):
    code = HEADER + '    assert FIXED == "1"\n'
    assert run_test(code, tmp_path / "f", "http://x", fixed=True)["outcome"] == "pass"
    assert run_test(code, tmp_path / "b", "http://x", fixed=False)["outcome"] == "assert_fail"


def test_judge_rules_decide_without_a_model():
    v, meta = judge({}, "", {"outcome": "pass"})
    assert (v["verdict"], v["decided_by"], meta) == ("NOT_REPRODUCED", "rule", None)
    v, meta = judge({}, "", {"outcome": "error", "exc_type": "TimeoutError", "phase": "call", "message": "x"})
    assert (v["verdict"], v["decided_by"], meta) == ("TEST_ERROR", "rule", None)


def test_lint_requires_explicit_build_flag():
    ok = 'def test_x(page):\n    page.goto(f"{APP_URL}/index.html?fixed={FIXED}")\n'
    assert lint(ok) is None
    assert "fixed" in lint('def test_x(page):\n    page.goto(f"{APP_URL}/index.html")\n')
    assert "fixed" in lint('def test_x(page):\n    page.goto(f"{APP_URL}/index.html?fixed=0")\n')
    assert "import" in lint('import requests\n' + ok)
