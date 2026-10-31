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
