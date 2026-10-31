"""M9: judge training data from the 5 training-only bugs, labelled by the buggy/fixed oracle (no LLM labels).

Run from the reprocam folder:
    python scripts/gen_judge_data.py --plan --limit 20    # projected cost only
    python scripts/gen_judge_data.py --limit 20 --yes     # make up to 20 new rows (resumes)

For each training bug, Muse Spark Open writes tests on purpose in 6 variants (correct repro, wrong
assertion, missing step, broken selector, unrelated assertion, trivially passing). Each test runs on
the buggy build (?train=1&fixed=0) and the fixed build (?fixed=1); LABELS turns the two outcomes
into the verdict. Demo bugs 1-3 never appear here: they stay held out for evaluation.

Rows: data/judge_sft_rows.jsonl (chat format in "messages" + metadata); cells the table drops go to
data/judge_sft_dropped.jsonl. The M9 spend so far (both files) counts toward --max-cost.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from serve_store import store_running  # noqa: E402

from backend import testgen  # noqa: E402
from backend.judge import judge_input  # noqa: E402
from backend.runner import run_test  # noqa: E402

ROWS = ROOT / "data" / "judge_sft_rows.jsonl"
DROPPED = ROOT / "data" / "judge_sft_dropped.jsonl"
WORK = ROOT / "runs" / "judge_data"
QUERY = "train=1"  # turns the training-only bugs on (buggy build only)

# BUILD_PLAN M9: all 9 buggy x fixed outcome pairs. None = ambiguous, the row is dropped.
LABELS = {
    ("assert_fail", "pass"): "REPRODUCED",            # fails only when the bug is present
    ("assert_fail", "assert_fail"): "NOT_REPRODUCED",  # fails for a reason unrelated to the bug
    ("assert_fail", "error"): None,                   # ambiguous: test breaks on the fixed build
    ("pass", "pass"): "NOT_REPRODUCED",                # never exercises the bug
    ("pass", "assert_fail"): "NOT_REPRODUCED",         # asserts the opposite of the claim
    ("pass", "error"): "NOT_REPRODUCED",               # doesn't reproduce on buggy
    ("error", "pass"): "TEST_ERROR",                   # broken on buggy
    ("error", "assert_fail"): "TEST_ERROR",            # broken on buggy
    ("error", "error"): "TEST_ERROR",                  # broken test
}

SYSTEM = ('You judge whether a generated Playwright test reproduced the bug a tester reported. '
          'Answer with JSON only: {"verdict": "REPRODUCED" | "NOT_REPRODUCED" | "TEST_ERROR"}')

# The training bugs as a tester would report them. Steps name testids from the element map.
BUGS = {
    "count_after_remove": {
        "steps": [("goto", "home page", None, "index.html"), ("click", "Linen Tea Towels card", "product-card-linen-towels", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "Home", "nav-home", None),
                  ("click", "Pebble Night Light card", "product-card-pebble-light", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "Basket", "nav-cart", None),
                  ("click", "Remove on the towels line", "line-remove", None)],
        "claim": {"summary": "After removing a line, the basket badge still counts it.",
                  "expected": "The basket badge shows 1 after removing one of two lines.",
                  "actual": "The badge still says Basket 2 with only the night light left.", "element": "basket badge"}},
    "subtotal_rounding": {
        "steps": [("goto", "home page", None, "index.html"), ("click", "Linen Tea Towels card", "product-card-linen-towels", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "View basket", "view-cart", None),
                  ("click", "+ on the towels line", "qty-plus", None), ("click", "+ on the towels line", "qty-plus", None)],
        "claim": {"summary": "With quantity 3 the line and subtotal are rounded to whole dollars.",
                  "expected": "3 x $27.60 = $82.80 for the line and the subtotal.",
                  "actual": "The line total and subtotal show $83.00.", "element": "subtotal"}},
    "detail_price": {
        "steps": [("goto", "home page", None, "index.html"),
                  ("click", "Indigo Weave Cushion Cover card", "product-card-indigo-cushion", None)],
        "claim": {"summary": "The cushion's product page shows a different price than the shop list.",
                  "expected": "The product page shows $32.00, as in the list.",
                  "actual": "The product page shows $23.00 while the list says $32.00.", "element": "product price"}},
    "confirm_total_zero": {
        "steps": [("goto", "home page", None, "index.html"), ("click", "Pebble Night Light card", "product-card-pebble-light", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "View basket", "view-cart", None),
                  ("click", "Checkout", "checkout-button", None), ("fill", "Full name", "checkout-name", "Ada Tester"),
                  ("fill", "Email", "checkout-email", "ada@example.com"), ("fill", "Street address", "checkout-address", "12 Harbor Lane"),
                  ("fill", "City", "checkout-city", "Albany"), ("fill", "ZIP code", "checkout-zip", "10001"),
                  ("click", "Place order", "place-order", None)],
        "claim": {"summary": "The order confirmation says nothing was charged.",
                  "expected": "The confirmation shows the basket total, $18.50.",
                  "actual": "The confirmation says Total charged $0.00.", "element": "total charged"}},
    "remove_wrong_line": {
        "steps": [("goto", "home page", None, "index.html"), ("click", "Linen Tea Towels card", "product-card-linen-towels", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "Home", "nav-home", None),
                  ("click", "Pebble Night Light card", "product-card-pebble-light", None),
                  ("click", "Add to basket", "add-to-cart", None), ("click", "Basket", "nav-cart", None),
                  ("click", "Remove on the night light line", "line-remove", None)],
        "claim": {"summary": "Remove deletes a different line than the one clicked.",
                  "expected": "Removing the night light leaves the towels in the basket.",
                  "actual": "The towels disappear and the night light stays.", "element": "basket lines"}},
}

VARIANTS = {
    "correct": "Write the test as described: replay the steps and assert the claim's expected behaviour.",
    "wrong_assertion": "For this test, deliberately make the final assertion expect a wrong value (a different "
                       "amount, count or text than correct behaviour), while replaying all the steps.",
    "missing_step": "For this test, deliberately leave out one of the steps that is needed to trigger the bug, "
                    "then assert the claim's expected behaviour.",
    "broken_selector": "For this test, deliberately use one testid that does not exist in the element map for "
                       "one of the steps.",
    "unrelated_assert": "For this test, replay the steps but make the final assertion check an unrelated element "
                        "that behaves correctly, not the one in the claim.",
    "trivial_pass": "For this test, replay the steps but only assert something that is always true, such as the "
                    "page header being visible.",
}


def label(buggy: str, fixed: str) -> str | None:
    """Oracle label for one test from its buggy-build and fixed-build outcomes (None = drop the row)."""
    return LABELS[(buggy, fixed)]


def steps_json(bug: str) -> dict:
    spec = BUGS[bug]
    return {"app_url": "http://localhost:5173",
            "steps": [{"n": i, "action": a, "target": t, "selector_hint": h, "value": v, "frame_ref": 0}
                      for i, (a, t, h, v) in enumerate(spec["steps"], 1)],
            "bug_claim": {**spec["claim"], "frame_ref": 0}}


def combos():
    """Round-robin over repeats, variants and bugs, so any prefix is spread across all of them."""
    for rep in range(1, 100):
        for variant in VARIANTS:
            for bug in BUGS:
                yield bug, variant, rep


def existing() -> tuple[set, float]:
    keys, spent = set(), 0.0
    for f in (ROWS, DROPPED):
        if f.exists():
            for r in map(json.loads, f.read_text().splitlines()):
                keys.add((r["bug"], r["variant"], r["rep"]))
                spent += r.get("cost_usd") or 0
    return keys, spent


def make_row(bug: str, variant: str, rep: int, app_url: str) -> dict:
    steps = steps_json(bug)
    code, notes, meta = testgen.generate(steps, extra=VARIANTS[variant])
    work = WORK / f"{bug}-{variant}-{rep}"
    shutil.rmtree(work, ignore_errors=True)
    problem = testgen.lint(code)
    if problem:  # never run: counts as a broken test on both builds
        buggy = good = {"outcome": "error", "phase": "lint", "exc_type": "Lint", "message": problem}
    else:
        buggy = run_test(code, work / "buggy", app_url, fixed=False, query=QUERY)
        good = run_test(code, work / "fixed", app_url, fixed=True, query=QUERY)
    verdict = label(buggy["outcome"], good["outcome"])
    user = judge_input(steps["bug_claim"], code, buggy)
    return {
        "bug": bug, "variant": variant, "rep": rep, "label": verdict,
        "oracle": {"buggy": buggy["outcome"], "fixed": good["outcome"]},
        "test_hash": hashlib.sha256(code.encode()).hexdigest()[:12], "cost_usd": meta.get("cost_usd") or 0,
        "testgen_prompt": meta.get("prompt_version"), "effort": meta.get("effort"),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                     {"role": "assistant", "content": json.dumps({"verdict": verdict})}] if verdict else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="new rows to make in this run")
    ap.add_argument("--max-cost", type=float, default=20.0, help="cap for all M9 spend so far + this run (USD)")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    have, spent = existing()
    todo = [c for c in combos() if c not in have][: args.limit]
    per_row = 0.009  # one testgen call at low effort (~$0.007-0.01 logged); test runs are local and free
    print(f"{len(todo)} new rows · ~${per_row * len(todo):.2f} projected · M9 spent so far ${spent:.2f} "
          f"of ${args.max_cost:.2f} cap")
    if args.plan or not todo:
        return
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    app_url = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    ROWS.parent.mkdir(exist_ok=True)
    with store_running(app_url):
        for i, (bug, variant, rep) in enumerate(todo, 1):
            if spent + per_row > args.max_cost:
                print(f"Stopping: the next row would pass the ${args.max_cost:.2f} cap.")
                break
            started = time.time()
            row = make_row(bug, variant, rep, app_url)
            spent += row["cost_usd"]
            with (ROWS if row["label"] else DROPPED).open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"[{i}/{len(todo)}] {bug:<19} {variant:<16} buggy={row['oracle']['buggy']:<11} "
                  f"fixed={row['oracle']['fixed']:<11} -> {row['label'] or 'DROPPED'} · ${row['cost_usd']:.4f} · "
                  f"{time.time() - started:.0f}s")
    print(f"M9 spent so far: ${spent:.3f}")


if __name__ == "__main__":
    main()
