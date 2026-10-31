"""M4b: does reasoning effort change how often the verify loop succeeds, and what it costs?

Run from the reprocam folder:
    python scripts/effort_sweep.py --plan      # projected cost only, spends nothing
    python scripts/effort_sweep.py --yes       # run (resumes: finished cells are skipped)

3 bugs x {low, medium, high} x 3 repeats = 27 runs on LLM_PROVIDER (Fireworks), each starting from
the sample's cached steps.json, so understanding is identical across efforts and only test writing
and judging change effort. Known-good build on (?fixed=1); the SAM evidence step is skipped.
Score per run: REPRODUCED and verified against the known-good build.
Rows: data/effort_sweep.jsonl.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.agent import run_pipeline  # noqa: E402
from backend.llm import CALL_LOG  # noqa: E402

BUGS = {"bug1": "neg_total", "bug2": "qty_stepper", "bug3": "zip_hang"}
EFFORTS = ["low", "medium", "high"]
REPEATS = 3
OUT = ROOT / "data" / "effort_sweep.jsonl"
# Fireworks preflight (docs/preflight.md): reasoning tokens vs low on the same prompt
OUTPUT_GROWTH = {"low": 1.0, "medium": 392 / 220, "high": 588 / 220}


def done_cells() -> set:
    if not OUT.exists():
        return set()
    return {(r["bug"], r["effort"], r["rep"]) for r in map(json.loads, OUT.read_text().splitlines())}


def projected_cost() -> dict:
    """Per-attempt cost at low effort from logged testgen + judge calls, output scaled per effort."""
    p_in, p_out = float(os.environ["PRICE_FIREWORKS_IN"]), float(os.environ["PRICE_FIREWORKS_OUT"])
    rows = [json.loads(line) for line in CALL_LOG.read_text().splitlines()]
    calls = {s: [r for r in rows if r.get("stage") == s and r.get("provider") == "fireworks"
                 and r.get("effort") == "low" and r.get("prompt_tokens")] for s in ("testgen", "judge")}
    per_effort = {}
    for effort, growth in OUTPUT_GROWTH.items():
        per_attempt = sum(mean(r["prompt_tokens"] for r in calls[s]) * p_in / 1e6 +
                          mean(r["completion_tokens"] for r in calls[s]) * growth * p_out / 1e6 for s in calls)
        per_effort[effort] = per_attempt
    return {"per_attempt": per_effort, "samples": {s: len(c) for s, c in calls.items()}}


def run_cell(bug: str, effort: str, rep: int) -> dict:
    run_dir = ROOT / "runs" / "sweep" / f"{bug}-{effort}-{rep}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    for name in ("steps.json", "frames.json"):
        shutil.copy2(ROOT / "samples" / bug / name, run_dir / name)
    os.environ["EFFORT_TESTGEN"] = os.environ["EFFORT_JUDGE"] = effort
    started = time.time()
    try:
        r = run_pipeline(str(ROOT / "samples" / f"{bug}.mov"), bug_id=BUGS[bug], from_steps=True, run_dir=run_dir,
                         known_good="fixed", evidence=False)
    except Exception as e:  # noqa: BLE001  (a crashed run scores 0 and is recorded)
        r = {"verdict": "ERROR", "error": f"{e.__class__.__name__}: {e}", "model_calls": []}
    calls = [c for c in r.get("model_calls", []) if c.get("provider") == "fireworks"]
    return {
        "bug": bug, "effort": effort, "rep": rep, "verdict": r["verdict"], "confirmed": r.get("confirmed"),
        "success": r["verdict"] == "REPRODUCED" and r.get("confirmed") is True, "label": r.get("label"),
        "attempts": r.get("attempt"), "cost_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 5),
        "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
        "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
        "reasoning_tokens": sum(c.get("reasoning_tokens") or 0 for c in calls),
        "seconds": round(time.time() - started, 1), "testgen_prompt": r.get("testgen_prompt"),
        "provider": os.getenv("LLM_PROVIDER"), "error": r.get("error"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="print the projected cost and exit")
    ap.add_argument("--yes", action="store_true", help="spend without asking")
    args = ap.parse_args()

    todo = [(b, e, r) for b in BUGS for e in EFFORTS for r in range(1, REPEATS + 1) if (b, e, r) not in done_cells()]
    proj = projected_cost()
    print(f"Provider {os.getenv('LLM_PROVIDER')} · testgen {os.getenv('TESTGEN_PROMPT') or 'newest prompt'} · "
          f"{len(todo)} of {len(BUGS) * len(EFFORTS) * REPEATS} runs to do "
          f"(cost basis: {proj['samples']['testgen']} testgen + {proj['samples']['judge']} judge calls logged at low)")
    expected = worst = 0.0
    for effort in EFFORTS:
        n = sum(1 for t in todo if t[1] == effort)
        a = proj["per_attempt"][effort]
        expected += n * a * 1.4  # ~1.4 attempts per run so far (bug2 needs a retry)
        worst += n * a * 3
        print(f"  {effort:<6} {n:>2} runs · ~${a:.4f} per attempt (test + judge)")
    print(f"Projected: ~${expected:.2f} expected, ${worst:.2f} at most (every run using all 3 attempts). "
          f"About {len(todo) * 45 // 60}-{len(todo) * 90 // 60} min.")
    if args.plan or not todo:
        return
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    OUT.parent.mkdir(exist_ok=True)
    for i, (bug, effort, rep) in enumerate(todo, 1):
        row = run_cell(bug, effort, rep)
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[{i}/{len(todo)}] {bug} {effort:<6} #{rep}: {'OK ' if row['success'] else 'no '} "
              f"{row['label'] or row['verdict']} · {row['attempts']} att · ${row['cost_usd']:.4f} · {row['seconds']}s")


if __name__ == "__main__":
    main()
