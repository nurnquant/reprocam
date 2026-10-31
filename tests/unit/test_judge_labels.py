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


def test_missing_import_mutation_is_an_error_when_run(tmp_path):
    from backend.runner import run_test
    from backend.testgen import assemble
    from gen_judge_data import mutate
    code = assemble(mutate(BASE.replace('page.goto(url("index.html"))', 'page.set_content("<p>x</p>")'), "missing_import"))
    r = run_test(code, tmp_path, "http://localhost:5173", fixed=False)
    assert r["outcome"] == "error" and r["exc_type"].endswith("NameError")


def test_split_keeps_groups_on_one_side(tmp_path, monkeypatch):
    import gen_judge_data as g
    rows = [{"bug": "b", "variant": v, "rep": i, "group": f"g{i}", "label": "X"} for i in range(60) for v in ("correct", "mut_x")]
    monkeypatch.setattr(g, "ROWS", tmp_path / "rows.jsonl")
    monkeypatch.setattr(g, "EVAL", tmp_path / "eval.jsonl")
    monkeypatch.setattr(g, "TRAIN", tmp_path / "train.jsonl")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    g.ROWS.write_text("".join(json.dumps(r) + "\n" for r in rows))
    g.split()
    ev = [json.loads(line) for line in g.EVAL.read_text().splitlines()]
    tr = [json.loads(line) for line in g.TRAIN.read_text().splitlines()]
    assert len(ev) == 40 and len({r["group"] for r in ev}) == 40
    assert not {r["group"] for r in ev} & {r["group"] for r in tr}
    g.split()
    assert [json.loads(line) for line in g.EVAL.read_text().splitlines()] == ev  # fixed seed: same eval set
