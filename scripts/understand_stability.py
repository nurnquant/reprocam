"""How stable is understanding? Same cached frames + transcript, understanding x N per bug and prompt version.

Run from the reprocam folder:
    python scripts/understand_stability.py --plan
    python scripts/understand_stability.py --yes [--versions v1 v2] [--repeats 3]

"Steps correct" is checked against the key actions each demo bug needs (what tests/store/ does);
the checks name testids from the element map, never a specific model answer. Rows go to
data/understand_stability.jsonl. Frames come from runs/<bug>/ (all keyframes); nothing in
runs/ or samples/ is modified (each trial works on a scratch copy).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "understand_stability.jsonl"


def _acts(steps: dict) -> list[tuple[str, str | None, str]]:
    return [(s["action"], s.get("selector_hint"), str(s.get("value") or "")) for s in steps.get("steps", [])]


def check(bug: str, steps: dict) -> tuple[bool, str]:
    """(correct, why) for one understanding of a demo bug."""
    acts = _acts(steps)
    clicks = [h for a, h, _ in acts if a == "click"]
    if steps.get("shows_app") is False:
        return False, "said the recording doesn't show the app"
    if bug == "bug1":  # neg_total: towels in the basket, GLOW20 applied twice
        fills = [v for a, h, v in acts if a == "fill" and h == "promo-input"]
        if clicks.count("promo-apply") < 2 or sum(v.upper() == "GLOW20" for v in fills) < 2:
            return False, f"promo applied {clicks.count('promo-apply')}x"
        if "line-remove" in clicks:
            return False, "clicks Remove"
        return True, "applies GLOW20 twice"
    if bug == "bug2":  # qty_stepper: pebble light, "-" (not Remove), then checkout
        pebble = any("pebble-light" in v for a, _, v in acts if a == "goto") or "product-card-pebble-light" in clicks
        if "line-remove" in clicks:
            return False, "clicks Remove instead of -"
        if "qty-minus" not in clicks:
            return False, "no - click"
        if not pebble:
            return False, "wrong or missing product"
        return True, "pebble light, -, " + ("checkout" if "checkout-button" in clicks else "no checkout")
    if bug == "bug3":  # zip_hang: a ZIP starting with 0, then Place order
        zips = [v for a, h, v in acts if a == "fill" and h == "checkout-zip"]
        if not any(z.startswith("0") for z in zips):
            return False, f"ZIP {zips or 'missing'}"
        if "place-order" not in clicks:
            return False, "no Place order"
        return True, f"ZIP {zips[0]}, Place order"
    raise ValueError(bug)


def trial(bug: str, version: str) -> dict:
    from backend.understand import understand
    src = ROOT / "runs" / bug
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / bug
        work.mkdir()
        shutil.copytree(src / "keyframes", work / "keyframes")
        for name in ("frames.json", "transcript.json"):
            shutil.copy2(src / name, work / name)
        started = time.time()
        out = understand(work, version=version)
    ok, why = check(bug, out["steps"])
    return {"bug": bug, "version": version, "correct": ok, "why": why, "steps": _acts(out["steps"]),
            "shows_app": out["steps"].get("shows_app"), "cost_usd": out["meta"]["cost_usd"],
            "seconds": round(time.time() - started, 1), "provider": out["meta"]["provider"],
            "effort": out["meta"]["effort"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="+", default=["v1", "v2"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    bugs = ["bug1", "bug2", "bug3"]
    n = len(bugs) * len(args.versions) * args.repeats
    print(f"{n} understanding calls (~$0.02-0.03 each with ~13-20 keyframes): ~${n * 0.022:.2f}")
    if args.plan:
        return
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")
    OUT.parent.mkdir(exist_ok=True)
    for rep in range(1, args.repeats + 1):
        for bug in bugs:
            for version in args.versions:
                row = trial(bug, version) | {"rep": rep}
                with OUT.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{bug} {version} #{rep}: {'OK ' if row['correct'] else 'no '} {row['why']} · ${row['cost_usd']}")
    provider = os.getenv("LLM_PROVIDER", "meta").lower()  # rows from other providers are kept, not counted here
    rows = [r for r in map(json.loads, OUT.read_text().splitlines())
            if r["version"] in args.versions and r.get("provider") == provider]
    print(f"\ncorrect / runs ({provider})")
    for bug in bugs:
        cells = [f"{v}: {sum(r['correct'] for r in rows if r['bug'] == bug and r['version'] == v)}/"
                 f"{sum(1 for r in rows if r['bug'] == bug and r['version'] == v)}" for v in args.versions]
        print(f"  {bug}  " + "   ".join(cells))


if __name__ == "__main__":
    main()
