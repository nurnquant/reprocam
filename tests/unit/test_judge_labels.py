"""The M9 oracle label table: exactly the 9 buggy x fixed cells from BUILD_PLAN, nothing else."""
import itertools
import json
import re
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
    from gen_judge_data import ASSERT_MUTATIONS, PAGE_ELEMENTS, mutate
    last = 'expect(page.get_by_test_id("cart-count"), "badge").to_have_text("1")'
    assert mutate(BASE, "wrong_value").splitlines()[-1].strip() in (last.replace('"1"', '"0"'), last.replace('"1"', '"2"'))
    for kind in ASSERT_MUTATIONS:
        assert lint(assemble(mutate(BASE, kind))) is None
        assert mutate(BASE.replace(last, "pass"), kind) is None  # nothing to break without an expect()


def _variants(kind: str, last_line: str, n: int = 60) -> list[str]:
    """The mutated last expect() of n copies of BASE that differ only in a comment (so the seed differs)."""
    from gen_judge_data import mutate
    out = []
    for i in range(n):
        code = BASE.replace('    expect(page.get_by_test_id("cart-count"), "badge").to_have_text("1")', f"    # v{i}\n{last_line}")
        out.append(mutate(code, kind))
    return out


def test_wrong_value_varies_price_rounding_and_sign():
    line = '    expect(page.get_by_test_id("cart-subtotal"), "should be $82.80").to_have_text("$82.80")'
    news = {re.search(r'to_have_text\("([^"]+)"\)', m).group(1) for m in _variants("wrong_value", line)}
    assert "$83.00" in news and "-$82.80" in news and news & {"$18.50", "$27.60", "$32.00", "$64.00"}  # all three kinds
    assert "$82.80" not in news
    for m in _variants("wrong_value", line, 10):  # the message follows the value, so it is no giveaway
        new = re.search(r'to_have_text\("([^"]+)"\)', m).group(1)
        assert f'"should be {new}"' in m


def test_wrong_element_uses_another_real_element_of_the_same_page_never_a_marker():
    from gen_judge_data import PAGE_ELEMENTS
    line = '    expect(page.get_by_test_id("cart-line-a").get_by_test_id("line-total"), "line").to_have_text("$82.80")'
    picked = {re.search(r'expect\(page\.get_by_test_id\("([\w-]+)"\)', m).group(1) for m in _variants("wrong_element", line)}
    assert picked <= set(PAGE_ELEMENTS["cart"]) and len(picked) > 1 and "build-mode" not in picked
    line = '    expect(page.get_by_test_id("product-detail").get_by_test_id("product-price"), "p").to_have_text("$32.00")'
    picked = {re.search(r'expect\(page\.get_by_test_id\("([\w-]+)"\)', m).group(1) for m in _variants("wrong_element", line)}
    assert picked <= {"product-title", "cart-count"}


def test_never_present_is_varied_and_really_never_present():
    from gen_judge_data import MISSING_TESTIDS, NEVER_PRESENT
    store = "".join(f.read_text() for f in (Path(__file__).resolve().parents[2] / "store").glob("*.*"))
    assert not [t for t in NEVER_PRESENT if t in store] and not [t for t in MISSING_TESTIDS if f'"{t}"' in store]
    line = '    expect(page.get_by_test_id("cart-subtotal"), "should be $82.80").to_have_text("$82.80")'
    muts = _variants("never_present", line)
    used = {t for m in muts for t in NEVER_PRESENT + MISSING_TESTIDS if f'"{t}"' in m}
    assert len(used) >= 10                                                  # no single phrase marks the copies
    assert any('get_by_test_id("cart-subtotal")' in m and "$82.80" not in m for m in muts)  # replaced in place
    assert any("get_by_text(" in m for m in muts) and any(any(f'"{t}"' in m for t in MISSING_TESTIDS) for m in muts)


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


def test_split_uses_only_the_slice_fills_eval_buckets_caps_mutations_and_keeps_groups_together(tmp_path, monkeypatch):
    import gen_judge_data as g
    fa = {"buggy": "assert_fail", "fixed": "assert_fail"}
    rows = []
    for i in range(70):  # each group: a correct test (in the slice), 3 mutated copies, one broken copy (not in the slice)
        rows.append({"bug": "b", "variant": "correct", "rep": i, "group": f"g{i}", "label": "REPRODUCED",
                     "oracle": {"buggy": "assert_fail", "fixed": "pass"}})
        rows += [{"bug": "b", "variant": f"mut_{k}", "rep": i, "group": f"g{i}", "label": "NOT_REPRODUCED", "oracle": fa}
                 for k in ("wrong_value", "wrong_element", "never_present")]
        rows.append({"bug": "b", "variant": "mut_x", "rep": i, "group": f"g{i}", "label": "TEST_ERROR",
                     "oracle": {"buggy": "error", "fixed": "error"}})
    rows += [{"bug": "b", "variant": "wrong_assertion", "rep": i, "group": f"w{i}", "label": "NOT_REPRODUCED",
              "oracle": fa} for i in range(25)]
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
    assert report["eval"] == {"REPRODUCED": 20, "NR_natural": 10, "NR_mutated": 10}
    assert len({r["group"] for r in ev}) == 40
    assert not {r["group"] for r in ev} & {r["group"] for r in tr}           # no group on both sides
    per_group = {}
    for r in tr:
        per_group[r["group"]] = per_group.get(r["group"], 0) + g.is_mutated(r)
    assert max(per_group.values()) == 1                                      # at most 1 mutated row per group
    assert len(g.ALL.read_text().splitlines()) == len(rows)                     # full set kept for reference
    g.split(min_train=10)
    assert [json.loads(line) for line in g.EVAL.read_text().splitlines()] == ev  # fixed seed: same eval set
    assert [json.loads(line) for line in g.TRAIN.read_text().splitlines()] == tr


def test_metrics_baseline_and_buckets():
    from judge_metrics import baseline, score
    rows = ([{"variant": "correct", "label": "REPRODUCED"}] * 20 + [{"variant": "wrong_assertion", "label": "NOT_REPRODUCED"}] * 10
            + [{"variant": "mut_wrong_value", "label": "NOT_REPRODUCED"}] * 10)
    b = baseline(rows)
    assert b["accuracy"] == 0.5 and b["balanced_accuracy"] == 0.5 and b["natural_nr_recall"] == 0 and b["mutated_nr_recall"] == 0
    preds = ["REPRODUCED"] * 20 + ["NOT_REPRODUCED"] * 5 + ["REPRODUCED"] * 5 + ["NOT_REPRODUCED"] * 10
    s = score(rows, preds)
    assert s["natural_nr_recall"] == 0.5 and s["mutated_nr_recall"] == 1.0 and s["balanced_accuracy"] == (1 + 0.75) / 2
