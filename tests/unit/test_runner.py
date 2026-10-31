"""runner classification + judge rule layer, on tiny inline pages (no store, no model calls)."""
import pytest

from backend.judge import judge
from backend.runner import run_test
from backend.testgen import assemble, lint

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


def test_lint_rejects_expect_message_that_reads_the_element():
    ok = assemble('def test_x(page):\n    page.goto(url("i.html"))\n')
    stale = ok + '    t = page.get_by_test_id("t")\n    expect(t, f"got {t.inner_text()}").to_have_text("1")\n'
    assert "inner_text" in lint(stale)
    assert lint(ok + '    expect(page.get_by_test_id("t"), "total should be 1").to_have_text("1")\n') is None


def test_judge_rule_catches_a_test_on_the_wrong_state():
    bug2_claim = {"summary": "Basket emptied but checkout still shows the old total.",
                  "expected": "Order total should update to $0.00.",
                  "actual": "Order total still shows $18.50 with Basket 0."}
    failure = {"outcome": "assert_fail", "exc_type": "builtins.AssertionError", "phase": "call",
               "message": "total should update\nExpected value: '$0.00'\nActual value: $89.00 \nCall log: ..."}
    v, meta = judge(bug2_claim, "", failure)
    assert (v["verdict"], v["decided_by"], meta) == ("TEST_ERROR", "rule", None)
    assert "wrong product/page" in v["feedback_for_generator"] and "$89.00" in v["reason"]


def test_judge_value_rule_lets_a_matching_value_through():
    from backend.judge import observed_actual, wrong_state
    bug1_claim = {"summary": "GLOW20 stacks", "expected": "discount stays -$20.00",
                  "actual": "Discount shows -$40.00 and Total -$12.40"}
    msg = "discount should stay\nExpected value: '-$20.00'\nActual value: -$40.00 \nCall log:"
    assert observed_actual(msg) == "-$40.00"
    assert wrong_state(bug1_claim, observed_actual(msg)) is None          # same value: model decides
    assert wrong_state(bug1_claim, None) is None                            # nothing observed: model decides
    assert wrong_state({"actual": "spinner never stops"}, "$5.00") is None  # claim names no amount


def test_action_timeout_is_10s_but_expect_timeouts_are_untouched(tmp_path):
    import time
    code = HEADER + '    page.get_by_test_id("missing").click()\n'
    t = time.time()
    r = run_test(code, tmp_path / "a", "http://x", fixed=False)
    assert r["outcome"] == "error" and r["exc_type"].endswith("TimeoutError") and "10000ms" in r["message"]
    assert time.time() - t < 25
    code = HEADER + '    expect(page.get_by_test_id("never")).to_be_visible(timeout=12000)\n'
    r = run_test(code, tmp_path / "b", "http://x", fixed=False)
    assert r["outcome"] == "assert_fail" and "12000ms" in r["message"]
