"""The M9 oracle label table: exactly the 9 buggy x fixed cells from BUILD_PLAN, nothing else."""
import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from gen_judge_data import BUGS, LABELS, VARIANTS, combos, label, steps_json  # noqa: E402

PLAN = {  # BUILD_PLAN.md, M9 label table
    ("assert_fail", "pass"): "REPRODUCED",
    ("assert_fail", "assert_fail"): "NOT_REPRODUCED",
    ("assert_fail", "error"): None,
    ("pass", "pass"): "NOT_REPRODUCED",
    ("pass", "assert_fail"): "NOT_REPRODUCED",
    ("pass", "error"): "NOT_REPRODUCED",
    ("error", "pass"): "TEST_ERROR",
    ("error", "assert_fail"): "TEST_ERROR",
    ("error", "error"): "TEST_ERROR",
}


@pytest.mark.parametrize("buggy, fixed", list(itertools.product(["pass", "assert_fail", "error"], repeat=2)))
def test_every_cell_matches_the_plan(buggy, fixed):
    assert label(buggy, fixed) == PLAN[(buggy, fixed)]


def test_table_has_exactly_nine_cells_and_one_dropped():
    assert set(LABELS) == set(PLAN) and len(LABELS) == 9
    assert [k for k, v in LABELS.items() if v is None] == [("assert_fail", "error")]


def test_training_data_never_uses_the_demo_bugs():
    assert not {"neg_total", "qty_stepper", "zip_hang"} & set(BUGS)
    store_registry = (Path(__file__).resolve().parents[2] / "store" / "bugs.js").read_text()
    for bug in BUGS:  # each one is registered as a training-only bug in the store
        assert f'{bug}: {{ on: true, set: "training" }}' in store_registry


def test_steps_use_only_real_testids_and_combos_spread_over_bugs():
    dom_map = json.loads((Path(__file__).resolve().parents[2] / "data" / "dom_map.json").read_text())
    testids = {r["testid"] for r in dom_map if r.get("testid")}
    for bug in BUGS:
        hints = {s["selector_hint"] for s in steps_json(bug)["steps"] if s["selector_hint"]}
        assert hints <= testids, hints - testids
    first = list(itertools.islice(combos(), len(BUGS) * 2))
    assert {b for b, _, _ in first} == set(BUGS) and len({v for _, v, _ in first}) == 2 and len(VARIANTS) == 6


BASE = '''from playwright.sync_api import expect

def test_reproduces_bug(page):
    page.goto(url("index.html"))
    page.get_by_test_id("product-card-linen-towels").click()
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("cart-count"), "badge").to_have_text("1")
'''


def test_mutations_break_the_test_the_intended_way():
    from backend.testgen import assemble, lint
    from gen_judge_data import mutate
    sel = mutate(BASE, "broken_selector")
    assert 'get_by_test_id("product-card-linen-towels-old").click()' in sel and '"cart-count"' in sel  # action, not expect
    assert "started = time.monotonic()" in mutate(BASE, "missing_import")
    assert 'url("confirmation.html")' in mutate(BASE, "wrong_page")
    for kind in ("broken_selector", "missing_import", "wrong_page"):
        assert lint(assemble(mutate(BASE, kind))) is None  # still runs, so the oracle labels it
    assert mutate("x = 1\n", "broken_selector") is None


def test_assertion_mutations_make_the_claim_assertion_wrong():
    from backend.testgen import assemble, lint
    from gen_judge_data import ASSERT_MUTATIONS, mutate
    last = 'expect(page.get_by_test_id("cart-count"), "badge").to_have_text("1")'
    assert 'expect(page.get_by_test_id("cart-count"), "badge").to_have_text("2")' in mutate(BASE, "wrong_value")
    money = BASE.replace(last, 'expect(page.get_by_test_id("cart-subtotal"), "should be $82.80").to_have_text("$82.80")')
    assert mutate(money, "wrong_value").count("$82.81") == 2  # the message follows, so it is no giveaway
    count = BASE.replace(last, 'expect(page.get_by_test_id("cart-line-pebble-light"), "gone").to_have_count(0)')
    assert ".to_have_count(1)" in mutate(count, "wrong_value")
    chained = BASE.replace('page.get_by_test_id("cart-count")', 'page.get_by_test_id("cart-line-a").get_by_test_id("line-total")')
    assert 'expect(page.get_by_test_id("build-mode"), "badge").to_have_text("1")' in mutate(chained, "wrong_element")
    never = mutate(BASE, "never_present").splitlines()
    i = next(n for n, ln in enumerate(never) if "get_by_text(" in ln)
    assert never[i + 1].strip() == last  # waits for the missing text first, before the claim assertion
    for kind in ASSERT_MUTATIONS:
        assert lint(assemble(mutate(BASE, kind))) is None
        assert mutate(BASE.replace(last, "pass"), kind) is None  # nothing to break without an expect()


def test_oracle_fixes_only_the_claimed_bug():
    from gen_judge_data import oracle_query
    assert oracle_query("detail_price") == "train=1&fixonly=detail_price"


def test_missing_import_mutation_is_an_error_when_run(tmp_path):
    from backend.runner import run_test
    from backend.testgen import assemble
    from gen_judge_data import mutate
    code = assemble(mutate(BASE.replace('page.goto(url("index.html"))', 'page.set_content("<p>x</p>")'), "missing_import"))
    r = run_test(code, tmp_path, "http://localhost:5173", fixed=False)
    assert r["outcome"] == "error" and r["exc_type"].endswith("NameError")


def test_split_uses_only_the_failed_assertion_slice_balances_eval_and_keeps_groups_together(tmp_path, monkeypatch):
    import gen_judge_data as g
    rows = []
    for i in range(70):  # each group: a correct test (in the slice) + a broken copy (error: not in the slice)
        rows.append({"bug": "b", "variant": "correct", "rep": i, "group": f"g{i}", "label": "REPRODUCED",
                     "oracle": {"buggy": "assert_fail", "fixed": "pass"}})
        rows.append({"bug": "b", "variant": "mut_x", "rep": i, "group": f"g{i}", "label": "TEST_ERROR",
                     "oracle": {"buggy": "error", "fixed": "error"}})
        if i < 10:  # some groups hold both slice labels
            rows.append({"bug": "b", "variant": "mut_wrong_value", "rep": i, "group": f"g{i}",
                         "label": "NOT_REPRODUCED", "oracle": {"buggy": "assert_fail", "fixed": "assert_fail"}})
    rows += [{"bug": "b", "variant": "wrong_assertion", "rep": i, "group": f"w{i}", "label": "NOT_REPRODUCED",
              "oracle": {"buggy": "assert_fail", "fixed": "assert_fail"}} for i in range(25)]
    rows += [{"bug": "b", "variant": "trivial", "rep": i, "group": f"t{i}", "label": "NOT_REPRODUCED",
              "oracle": {"buggy": "pass", "fixed": "pass"}} for i in range(30)]
    for name in ("ROWS", "EVAL", "TRAIN", "ALL", "DROPPED"):
        monkeypatch.setattr(g, name, tmp_path / f"{name}.jsonl")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    g.ROWS.write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = g.split(min_train=10)
    ev = [json.loads(line) for line in g.EVAL.read_text().splitlines()]
    tr = [json.loads(line) for line in g.TRAIN.read_text().splitlines()]
    assert all(r["oracle"]["buggy"] == "assert_fail" for r in ev + tr)       # the slice only
    assert report["eval"] == {"REPRODUCED": 20, "NOT_REPRODUCED": 20}        # balanced
    assert len({r["group"] for r in ev}) == 40
    assert not {r["group"] for r in ev} & {r["group"] for r in tr}           # no group on both sides
    assert len(tr) == 70 + 10 + 25 - sum(1 for r in rows if r["group"] in {e["group"] for e in ev} and g.in_slice(r))
    assert len(g.ALL.read_text().splitlines()) == len(rows)                     # full set kept for reference
    g.split(min_train=10)
    assert [json.loads(line) for line in g.EVAL.read_text().splitlines()] == ev  # fixed seed: same eval set
