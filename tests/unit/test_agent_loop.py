"""The verify loop's decisions with known-good mode, with test writing, runs and judging faked."""
import json

import pytest

from backend import agent


@pytest.fixture
def run_dir(tmp_path):
    claim = {"summary": "s", "expected": "e", "actual": "a", "element": "x", "frame_ref": 0}
    (tmp_path / "steps.json").write_text(json.dumps({"app_url": "http://x", "steps": [], "bug_claim": claim}))
    return tmp_path


def fake(monkeypatch, buggy, good, verdicts):
    """buggy/good/verdicts: one entry per attempt."""
    n = {"gen": 0}
    monkeypatch.setattr(agent.testgen, "generate", lambda steps, prev: (n.update(gen=n["gen"] + 1) or
                        agent.testgen.assemble(f'def test_x(page):\n    page.goto(url("i.html", a="{n["gen"]}"))\n'),
                        "notes", {"model": "m", "provider": "p", "effort": "low", "cost_usd": 0.0,
                                   "prompt_version": "testgen v0"}))

    def run_test(code, workdir, app_url, fixed):
        out = (good if fixed else buggy)[n["gen"] - 1]
        return {"outcome": out, "exc_type": "AssertionError", "phase": "call", "message": f"Actual value: {out}",
                "output": "", "screenshot": None}
    monkeypatch.setattr(agent, "run_test", run_test)
    monkeypatch.setattr(agent, "judge", lambda claim, code, result: (
        {"verdict": verdicts[n["gen"] - 1], "decided_by": "model", "reason": "r", "feedback_for_generator": "f"},
        None))
    monkeypatch.setattr(agent, "log_verdict", lambda *a, **k: None)


def test_known_good_failure_retries_then_confirms(monkeypatch, run_dir):
    fake(monkeypatch, ["assert_fail"] * 2, ["assert_fail", "pass"], ["REPRODUCED"] * 2)
    out = agent.run_pipeline("bug2.mov", from_steps=True, run_dir=run_dir, known_good="fixed")
    assert (out["attempt"], out["confirmed"], out["tone"]) == (2, True, "good")
    assert out["label"] == "REPRODUCED · verified against known-good build"


def test_falls_back_to_the_unconfirmed_reproduction(monkeypatch, run_dir):
    fake(monkeypatch, ["assert_fail", "assert_fail", "pass"], ["assert_fail"] * 3,
         ["REPRODUCED", "NOT_REPRODUCED", "NOT_REPRODUCED"])
    out = agent.run_pipeline("bug2.mov", from_steps=True, run_dir=run_dir, known_good="fixed")
    assert (out["verdict"], out["attempt"], out["confirmed"], out["tone"]) == ("REPRODUCED", 1, False, "warn")
    assert out["label"] == "REPRODUCED · NOT CONFIRMED (also fails on fixed build)"
    assert "NOT CONFIRMED" in (run_dir / "ticket.md").read_text()


def test_without_known_good_the_first_reproduction_ends_the_run(monkeypatch, run_dir):
    fake(monkeypatch, ["assert_fail"], ["assert_fail"], ["REPRODUCED"])
    out = agent.run_pipeline("bug2.mov", from_steps=True, run_dir=run_dir, known_good="")
    assert (out["attempt"], out["confirmed"], out["fixcheck"]) == (1, None, None)
    assert "not verified" in out["label"]


def test_stops_before_any_test_when_the_recording_is_not_the_app(monkeypatch, run_dir):
    steps = json.loads((run_dir / "steps.json").read_text()) | {"shows_app": False}
    (run_dir / "steps.json").write_text(json.dumps(steps))
    monkeypatch.setattr(agent.testgen, "generate", lambda *a: pytest.fail("no test should be written"))
    out = agent.run_pipeline("phone.mov", from_steps=True, run_dir=run_dir, known_good="fixed")
    assert (out["verdict"], out["attempt"], out["label"], out["tone"]) == (
        "NOT_APP", 0, "Not a recording of the app under test", "bad")
    assert not list(run_dir.glob("attempt_*")) and not (run_dir / "ticket.md").exists()
