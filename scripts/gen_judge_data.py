"""M9: judge training data from the 5 training-only bugs, labelled by the buggy/fixed oracle (no LLM labels).

Run from the reprocam folder:
    python scripts/gen_judge_data.py --plan --limit 20    # projected cost only
    python scripts/gen_judge_data.py --limit 20 --yes     # make up to 20 new rows (resumes)

For each training bug, Muse Spark Open writes tests in several variants (correct repro, wrong assertion,
missing step, unrelated assertion, trivially passing; weighted by PLAN). The model often ignores
"deliberately break it" instructions, so broken tests are also made by code: every correct test gets one
mutated copy (broken selector on an action, missing import, or wrong start page, in rotation) at no
extra model cost. Each test runs on the buggy build (?train=1, all 8 bugs on) and on the same build with
only the claimed bug fixed (?train=1&fixonly=<bug>), so a test that trips over a different bug fails on
both and is not credited as a reproduction. LABELS turns the two outcomes into the verdict. Demo bugs 1-3
are never claimed here: they stay held out.

    python scripts/gen_judge_data.py --relabel  # re-run every row's oracle with ?fixonly (local, no model calls)
    python scripts/gen_judge_data.py --mutate   # wrong value / wrong element / never-present text copies (local)
    python scripts/gen_judge_data.py --split    # slice-only train/eval: eval 20 REPRODUCED / 10 natural NR / 10 mutated NR (seed 1031)


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
from judge_metrics import bucket, is_mutated  # noqa: E402,F401  (eval buckets, shared with the eval code)

ROWS = ROOT / "data" / "judge_sft_rows.jsonl"
DROPPED = ROOT / "data" / "judge_sft_dropped.jsonl"
WORK = ROOT / "runs" / "judge_data"
QUERY = "train=1"  # turns the training-only bugs on (buggy build only)


def oracle_query(bug: str) -> str:
    """The oracle's "fixed" run: the buggy build with only the claimed bug turned off."""
    return f"{QUERY}&fixonly={bug}"

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


# Model calls per bug and variant for the full set (~445 calls -> ~600 rows with mutations).
# wrong_assertion was raised from 18 to 48 for more model-written (natural) NOT_REPRODUCED rows in the slice.
PLAN = {"correct": 31, "wrong_assertion": 48, "missing_step": 13, "unrelated_assert": 13, "trivial_pass": 14}
MUTATIONS = ["broken_selector", "missing_import", "wrong_page"]  # one per correct test, in rotation
# Every correct test also gets one copy of each of these (--mutate): its claim assertion is made wrong
ASSERT_MUTATIONS = ["wrong_value", "wrong_element", "never_present"]
# Store facts the mutations draw from (store/app.js, store/*.html)
PRICES = [8900, 14500, 1850, 6400, 2760, 3200]  # cents, the six products
PAGE_ELEMENTS = {  # page-level elements with text, one of each per page (line-* repeat, so they're left out)
    "cart": ["cart-subtotal", "order-total", "cart-count"],
    "product": ["product-price", "product-title", "cart-count"],
    "checkout": ["checkout-total", "cart-count"],
    "confirmation": ["confirmation-total", "order-number", "cart-count"],
}
PAGE_PREFIXES = {"confirmation": ("confirmation-", "order-number", "order-confirmation"),
                 "checkout": ("checkout-", "place-order"), "product": ("product-", "add-to-cart", "added-message", "view-cart"),
                 "cart": ("cart", "line-", "order-total", "discount-total", "promo-", "qty-")}
NEVER_PRESENT = [  # none of these appear anywhere in the store (tests/unit/test_judge_labels.py checks)
    "Gift wrap: added", "Free delivery unlocked", "Loyalty points earned: 40", "Saved to your wishlist",
    "Estimated delivery: 2-3 days", "Only 2 left in stock", "Basket saved for later", "Thanks for shopping with us",
    "Parcel handed to courier", "Promo code expired", "Payment authorised", "Express shipping selected",
    "Subscribe and save 5%", "Back in stock soon", "VAT included", "Pay in 3 instalments", "Order updated",
    "Price match applied", "Member price", "Click and collect available", "Receipt emailed", "Item reserved",
    "Delivery address confirmed", "Basket total updated",
]
MISSING_TESTIDS = ["delivery-estimate", "gift-wrap-note", "loyalty-points", "stock-note", "receipt-link",
                   "order-status", "basket-saved", "price-match", "payment-status", "member-price"]
MESSAGES = ["{} should be shown", "page should mention {}", "{} message should appear", "expect {} to be visible",
            "{} should be on the page", "shows {}"]
EVAL = ROOT / "data" / "judge_sft_eval.jsonl"
TRAIN = ROOT / "data" / "judge_sft_train.jsonl"
ALL = ROOT / "data" / "judge_data_all.jsonl"


def mutate(code: str, kind: str) -> str | None:
    """A deliberately broken copy of a working test, or None if this test has nothing to break."""
    import re
    head, sep, body = code.partition("def test_")
    if not sep:
        return None
    body = sep + body
    if kind == "broken_selector":  # a testid that doesn't exist, on a click or fill (an action, not an expect)
        m = re.search(r'get_by_test_id\("([\w-]+)"\)(?=\.(?:click|fill)\()', body)
        return head + body[:m.start(1)] + m.group(1) + "-old" + body[m.end(1):] if m else None
    if kind == "missing_import":  # uses a module the file never imports
        lines = body.split("\n")
        return head + "\n".join(lines[:1] + ["    started = time.monotonic()"] + lines[1:])
    if kind == "wrong_page":  # starts somewhere the steps can't be taken
        m = re.search(r'page\.goto\(url\("([^"]+)"', body)
        if not m:
            return None
        other = "confirmation.html" if not m.group(1).startswith("confirmation") else "index.html"
        return head + body[:m.start(1)] + other + body[m.end(1):]
    if kind in ASSERT_MUTATIONS:
        broken = _break_last_expect(body, kind)
        return head + broken if broken else None
    raise ValueError(kind)


def _break_last_expect(body: str, kind: str) -> str | None:
    """The test with its last expect() (the claim assertion) made wrong, or None if it can't be.
    Each kind draws from a varied pool (seeded by the test) so no fixed string marks a mutated test."""
    import random
    import re
    lines = body.split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("expect(")]
    if not idx:
        return None
    i = idx[-1]
    line = lines[i]
    rnd = random.Random(f"{kind}-{hashlib.sha256(body.encode()).hexdigest()}")
    if kind == "wrong_value":  # the message changes with the value, so it is no hint either
        new = _wrong_value(line, rnd)
        if new is None:
            return None
        lines[i] = new
        return "\n".join(lines)
    if kind == "wrong_element":  # same assertion on another real element of the same page
        m = re.match(r'(\s*expect\()page((?:\.get_by_test_id\("[\w-]+"\))+)', line)
        if not m:
            return None
        ids = re.findall(r'"([\w-]+)"', m.group(2))
        others = [t for t in PAGE_ELEMENTS[_page_of(ids[-1], body)] if t not in ids and not
                  (ids[-1] in ("nav-cart", "cart-count") and t == "cart-count")]
        lines[i] = m.group(1) + f'page.get_by_test_id("{rnd.choice(others)}")' + line[m.end():]
        return "\n".join(lines)
    if kind == "never_present":  # waits for text or an element the store never shows
        text = rnd.choice(NEVER_PRESENT)
        style = rnd.choice(["text", "testid", "replace"])
        lit = re.search(r'\.(?:to_have_text|to_contain_text)\("([^"]*)"\)', line)
        if style == "replace" and lit:
            lines[i] = line.replace(lit.group(1), text)  # in the message too, so it doesn't contradict the check
            return "\n".join(lines)
        indent = line[: len(line) - len(line.lstrip())]
        testid = rnd.choice(MISSING_TESTIDS)
        loc = f'page.get_by_test_id("{testid}")' if style == "testid" else f'page.get_by_text("{text}")'
        msg = rnd.choice(MESSAGES).format(testid.replace("-", " ") if style == "testid" else text.split(":")[0].lower())
        lines.insert(i, f'{indent}expect({loc}, "{msg}").to_be_visible()')
        return "\n".join(lines)
    raise ValueError(kind)


def _money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) // 100}.{abs(cents) % 100:02d}"


def _wrong_value(line: str, rnd) -> str | None:
    """A different expected value: another product's price, a rounded amount or a sign flip for money;
    one more or one fewer for counts. None when the assertion has no value to change."""
    import re
    m = re.search(r'\.(?:to_have_text|to_contain_text|to_have_value)\("([^"]*)"\)', line)
    if m:
        old = m.group(1)
        money = re.search(r"-?\$\d+\.\d\d", old)
        if money:
            amount = money.group(0)
            cents = round(float(amount.replace("$", "")) * 100)
            options = [_money(p) for p in PRICES if p != abs(cents)]
            if cents % 100:
                options.append(_money(round(cents / 100) * 100))  # rounded to whole dollars
            if cents:
                options.append(_money(-cents))                     # sign flipped
            new = old.replace(amount, rnd.choice(options))
        else:
            num = re.search(r"\d+", old)
            if not num:
                return None
            n = int(num.group(0))
            new = old[:num.start()] + str(n + 1 if n == 0 or rnd.random() < 0.5 else n - 1) + old[num.end():]
        return line.replace(old, new)
    m = re.search(r'\.to_have_count\((\d+)\)', line)
    if m:
        n = int(m.group(1))
        return line[:m.start(1)] + str(n + 1 if n == 0 or rnd.random() < 0.5 else n - 1) + line[m.end(1):]
    return None


def _page_of(testid: str, body: str) -> str:
    """Which store page an element belongs to (nav elements: the page the test ends on)."""
    for page, prefixes in PAGE_PREFIXES.items():
        if testid.startswith(prefixes):
            return page
    for t in reversed(__import__("re").findall(r'get_by_test_id\("([\w-]+)"\)', body)):
        if t not in ("nav-cart", "cart-count", "nav-home"):
            return _page_of(t, "")
    return "cart"


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
    """Model calls in PLAN proportions, interleaved so any prefix is spread across bugs and variants."""
    for rep in range(1, max(PLAN.values()) + 1):
        for variant, n in PLAN.items():
            if rep <= n:
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


def run_and_label(bug: str, variant: str, rep: int, code: str, app_url: str, cost: float, meta: dict,
                  group: str) -> dict:
    steps = steps_json(bug)
    work = WORK / f"{bug}-{variant}-{rep}"
    shutil.rmtree(work, ignore_errors=True)
    problem = testgen.lint(code)
    if problem:  # never run: counts as a broken test on both builds
        buggy = good = {"outcome": "error", "phase": "lint", "exc_type": "Lint", "message": problem}
    else:
        buggy = run_test(code, work / "buggy", app_url, fixed=False, query=QUERY)
        good = run_test(code, work / "fixed", app_url, fixed=False, query=oracle_query(bug))
    verdict = label(buggy["outcome"], good["outcome"])
    user = judge_input(steps["bug_claim"], code, buggy)
    return {
        "bug": bug, "variant": variant, "rep": rep, "label": verdict, "group": group,
        "oracle": {"buggy": buggy["outcome"], "fixed": good["outcome"], "fixed_build": "fixonly"},
        "test_hash": hashlib.sha256(code.encode()).hexdigest()[:12], "cost_usd": cost,
        "testgen_prompt": meta.get("prompt_version"), "effort": meta.get("effort"),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                     {"role": "assistant", "content": json.dumps({"verdict": verdict})}] if verdict else None,
    }


def make_rows(bug: str, variant: str, rep: int, app_url: str) -> list[dict]:
    """One model-written test (+ a mutated copy if it's a correct one). Same group = never split apart."""
    code, notes, meta = testgen.generate(steps_json(bug), extra=VARIANTS[variant])
    group = f"{bug}-{variant}-{rep}"
    rows = [run_and_label(bug, variant, rep, code, app_url, meta.get("cost_usd") or 0, meta, group)]
    if variant == "correct":
        kind = MUTATIONS[(rep - 1) % len(MUTATIONS)]
        broken = mutate(code, kind)
        if broken:
            rows.append(run_and_label(bug, f"mut_{kind}", rep, broken, app_url, 0.0, meta, group))
    return rows


def saved_code(row: dict) -> str | None:
    """The test a row was made from (its run folder), checked against the row's hash. None for tests that
    never ran (failed lint): those stay TEST_ERROR on both builds."""
    f = WORK / f"{row['bug']}-{row['variant']}-{row['rep']}" / "buggy" / "test_repro.py"
    if not f.exists():
        return None
    code = f.read_text()
    if hashlib.sha256(code.encode()).hexdigest()[:12] != row["test_hash"]:
        raise RuntimeError(f"{f} does not match the row's test_hash")
    return code


def _load_all() -> list[dict]:
    return [json.loads(line) for f in (ROWS, DROPPED) if f.exists() for line in f.read_text().splitlines()]


def _write_all(rows: list[dict]) -> None:
    ROWS.write_text("".join(json.dumps(r) + "\n" for r in rows if r["label"]))
    DROPPED.write_text("".join(json.dumps(r) + "\n" for r in rows if not r["label"]))


def _set_label(row: dict, fixed_outcome: str) -> None:
    row["oracle"] = {**row["oracle"], "fixed": fixed_outcome, "fixed_build": "fixonly"}
    row["label"] = label(row["oracle"]["buggy"], fixed_outcome)
    if row["messages"]:  # the judge's input is the buggy run, unchanged; only the answer moves
        row["messages"] = row["messages"][:2] + [{"role": "assistant", "content": json.dumps({"verdict": row["label"]})}]


def _parallel(fn, items, workers):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    app_url = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    out = []
    with store_running(app_url), ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(fn, item, app_url) for item in items]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                out.append(fut.result())
            except Exception as e:  # noqa: BLE001  (that row is left as it was; re-running picks it up)
                print(f"  failed: {e.__class__.__name__}: {str(e)[:120]}", flush=True)
            if n % 50 == 0 or n == len(items):
                print(f"  {n}/{len(items)}", flush=True)
    return out


def relabel(workers: int = 6) -> None:
    """Re-run every row's oracle on ?train=1&fixonly=<claimed bug> (local runs, no model calls). Rows made
    before this keep their old label as label_fixed_all, so the change can be counted."""
    from collections import Counter
    rows = _load_all()
    todo = [r for r in rows if r["oracle"].get("fixed_build") != "fixonly"]
    print(f"relabel: {len(todo)} of {len(rows)} rows need a fixonly oracle run")

    def one(row, app_url):
        code = saved_code(row)
        old = row["label"]
        if code is None:
            fixed_outcome = row["oracle"]["fixed"]  # never ran (lint): error on both builds, as before
        else:
            work = WORK / f"{row['bug']}-{row['variant']}-{row['rep']}"
            fixed_outcome = run_test(code, work / "fixonly", app_url, fixed=False,
                                     query=oracle_query(row["bug"]))["outcome"]
        row.setdefault("label_fixed_all", old)
        row.setdefault("oracle_fixed_all", row["oracle"]["fixed"])
        _set_label(row, fixed_outcome)
        return row

    _parallel(one, todo, workers)
    _write_all(rows)
    changed = Counter((r["variant"], r["label_fixed_all"], r["label"]) for r in todo if r["label_fixed_all"] != r["label"])
    print(f"relabel: {sum(changed.values())} of {len(todo)} labels changed")
    for (variant, old, new), n in sorted(changed.items()):
        print(f"  {variant:<20} {old} -> {new or 'DROPPED'}: {n}")


def add_mutations(workers: int = 6) -> None:
    """One copy of every correct test per ASSERT_MUTATIONS kind, in the correct test's group (local runs)."""
    from collections import Counter
    rows = _load_all()
    have = {(r["bug"], r["variant"], r["rep"]) for r in rows}
    todo = []
    for r in rows:
        if r["variant"] != "correct":
            continue
        code = saved_code(r)
        for kind in ASSERT_MUTATIONS:
            broken = mutate(code, kind) if code else None
            if broken and (r["bug"], f"mut_{kind}", r["rep"]) not in have:
                todo.append((r, kind, broken))
    print(f"mutate: {len(todo)} new rows from {sum(r['variant'] == 'correct' for r in rows)} correct tests")

    def one(item, app_url):
        r, kind, broken = item
        return run_and_label(r["bug"], f"mut_{kind}", r["rep"], broken, app_url, 0.0,
                             {"prompt_version": r.get("testgen_prompt"), "effort": r.get("effort")}, _group(r))

    new = _parallel(one, todo, workers)
    _write_all(rows + new)
    c = Counter((r["variant"], r["oracle"]["buggy"], r["label"]) for r in new)
    for (variant, buggy, lab), n in sorted(c.items()):
        print(f"  {variant:<20} buggy={buggy:<11} {lab or 'DROPPED'}: {n}")


def in_slice(row: dict) -> bool:
    """What the model judge sees in production: the rule layer handles passes and crashes first, so the
    model only judges tests that failed an assertion on the buggy build (labels: REPRODUCED or NOT_REPRODUCED)."""
    return row.get("label") is not None and row["oracle"]["buggy"] == "assert_fail"


def _group(r: dict) -> str:
    return r.get("group") or f"{r['bug']}-{r['variant']}-{r['rep']}"


EVAL_PLAN = {"REPRODUCED": 20, "NR_natural": 10, "NR_mutated": 10}


def split(seed: int = 1031, plan: dict | None = None, min_train: int = 200, max_mut_per_group: int = 1) -> dict:
    """Full set -> judge_data_all.jsonl (reference). Train/eval come from the failed-assertion slice only.
    Eval: plan[bucket] groups held out per bucket, BEFORE any training, one row of that bucket per group; the
    held groups' other rows are left out of training too, so no near-duplicate of an eval row is trained on.
    Train: every natural row of the other groups, plus at most max_mut_per_group mutated rows per group."""
    import random
    from collections import Counter
    plan = plan or EVAL_PLAN
    rows = [json.loads(line) for line in ROWS.read_text().splitlines()]
    dropped = [json.loads(line) for line in DROPPED.read_text().splitlines()] if DROPPED.exists() else []
    ALL.write_text("".join(json.dumps(r) + "\n" for r in rows + dropped))
    sliced = [r for r in rows if in_slice(r)]
    by_group = {}
    for r in sliced:
        by_group.setdefault(_group(r), []).append(r)
    rnd, held, eval_rows = random.Random(seed), set(), []
    # the rarest bucket picks its groups first, so groups holding several buckets can't all go to another
    for b in sorted(plan, key=lambda x: (sum(bucket(r) == x for r in sliced), x)):
        groups = sorted(g for g, rs in by_group.items() if g not in held and any(bucket(r) == b for r in rs))
        if len(groups) < plan[b]:
            print(f"WARNING: only {len(groups)} groups with a {b} row (eval wants {plan[b]})")
        for g in rnd.sample(groups, min(plan[b], len(groups))):
            held.add(g)
            eval_rows.append(random.Random(f"{seed}-{g}").choice(sorted(
                (r for r in by_group[g] if bucket(r) == b), key=lambda r: r["variant"])))
    train_rows, capped = [], 0
    for g in sorted(by_group):
        if g in held:
            continue
        muts = sorted((r for r in by_group[g] if is_mutated(r)), key=lambda r: r["variant"])
        keep = random.Random(f"{seed}-cap-{g}").sample(muts, min(max_mut_per_group, len(muts)))
        capped += len(muts) - len(keep)
        train_rows += [r for r in by_group[g] if not is_mutated(r)] + keep
    EVAL.write_text("".join(json.dumps(r) + "\n" for r in eval_rows))
    TRAIN.write_text("".join(json.dumps(r) + "\n" for r in train_rows))

    report = {"all": Counter(r["label"] for r in rows) + Counter({"DROPPED": len(dropped)}),
              "slice": Counter(bucket(r) for r in sliced), "train": Counter(bucket(r) for r in train_rows),
              "eval": Counter(bucket(r) for r in eval_rows),
              "train_variants": Counter((r["variant"], r["label"]) for r in train_rows),
              "eval_variants": Counter((r["variant"], r["label"]) for r in eval_rows),
              "left_out": sum(len(by_group[g]) for g in held) - len(eval_rows), "capped": capped}
    for name in ("all", "slice", "train", "eval"):
        c = report[name]
        print(f"  {name:<6} {sum(c.values()):>4} rows · " + " · ".join(f"{k} {v}" for k, v in sorted(c.items())))
    print(f"  {report['left_out']} sibling row(s) of eval rows used in neither · {capped} mutated row(s) over the "
          f"{max_mut_per_group}-per-group cap left out of train · files: {ALL.relative_to(ROOT)}, "
          f"{TRAIN.relative_to(ROOT)}, {EVAL.relative_to(ROOT)}")
    for name in ("train_variants", "eval_variants"):
        print(f"  {name}: " + " · ".join(f"{v}/{lab[:3]} {n}" for (v, lab), n in sorted(report[name].items())))
    if len(train_rows) < min_train:
        print(f"STOP: only {len(train_rows)} training rows in the failed-assertion slice (< {min_train}). "
              f"Generate more variants that reach an assertion before training.")
    return report


def project(todo: list, rows_now: list[dict]) -> None:
    """Projected cost and label mix, from the first batch's measured cost and labels per variant."""
    from collections import Counter
    cost = sum(r["cost_usd"] for r in rows_now if r["cost_usd"]) / max(1, sum(1 for r in rows_now if r["cost_usd"]))
    rates = {v: Counter(r["label"] for r in rows_now if r["variant"] == v) for v in PLAN}
    mix = Counter({k: n for r in rows_now if r.get("label") for k, n in [(r["label"], 1)]})
    for bug, variant, rep in todo:
        seen = sum(rates[variant].values())
        for lab, n in (rates[variant].items() if seen else [("NOT_REPRODUCED", 1)]):
            mix[lab] += n / (seen or 1)
        if variant == "correct":
            mix["TEST_ERROR"] += 1  # the mutated copy
    total = sum(mix.values())
    print(f"{len(todo)} model calls · ~{total:.0f} rows in total (incl. {len(rows_now)} already made) · "
          f"~${cost * len(todo):.2f} projected (${cost:.4f} per call, measured) · test runs are local and free")
    print("projected labels: " + " · ".join(f"{k} {v / total:.0%}" for k, v in sorted(mix.items())))


def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="model calls in this run (0 = the whole PLAN)")
    ap.add_argument("--max-cost", type=float, default=20.0, help="cap for all M9 spend so far + this run (USD)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--split", action="store_true", help="write the held-out eval and train files, then exit")
    ap.add_argument("--relabel", action="store_true", help="re-run every row's oracle with ?fixonly, then exit")
    ap.add_argument("--mutate", action="store_true", help="add the assertion mutations of correct tests, then exit")
    ap.add_argument("--export-binary", action="store_true",
                    help="write data/glimmer_upload_{train,eval}.jsonl from the split (binary instructions), then exit")
    args = ap.parse_args()
    if args.export_binary:
        from judge_metrics import write_upload_files
        return write_upload_files()
    if args.split:
        return split()
    if args.relabel:
        return relabel(args.workers)
    if args.mutate:
        return add_mutations(args.workers)

    have, spent = existing()
    todo = [c for c in combos() if c not in have]
    todo = todo[: args.limit] if args.limit else todo
    rows_now = [json.loads(line) for line in ROWS.read_text().splitlines()] if ROWS.exists() else []
    project(todo, rows_now)
    print(f"M9 spent so far ${spent:.2f} of ${args.max_cost:.2f} cap")
    if args.plan or not todo:
        return
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    app_url = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    os.environ.setdefault("LLM_RETRIES", "7")  # ~2 min of backoff: rides out a provider overload (503)
    ROWS.parent.mkdir(exist_ok=True)
    lock, done, state = Lock(), 0, {"spent": spent, "stop": False}

    def one(combo):
        if state["stop"]:
            return []
        return make_rows(*combo, app_url)

    with store_running(app_url), ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(one, c): c for c in todo}
        for fut in as_completed(futures):
            done += 1
            try:
                rows = fut.result()
            except Exception as e:  # noqa: BLE001  (one bad call must not stop the batch)
                print(f"[{done}/{len(todo)}] {futures[fut]} failed: {e.__class__.__name__}: {str(e)[:120]}")
                continue
            with lock:
                for row in rows:
                    state["spent"] += row["cost_usd"]
                    with (ROWS if row["label"] else DROPPED).open("a") as f:
                        f.write(json.dumps(row) + "\n")
                if state["spent"] > args.max_cost:
                    state["stop"] = True
            for row in rows:
                print(f"[{done}/{len(todo)}] {row['bug']:<19} {row['variant']:<20} buggy={row['oracle']['buggy']:<11} "
                      f"fixed={row['oracle']['fixed']:<11} -> {row['label'] or 'DROPPED'}")
    print(f"M9 spent so far: ${state['spent']:.3f}" + (" (stopped at the cap)" if state["stop"] else ""))


if __name__ == "__main__":
    main()
