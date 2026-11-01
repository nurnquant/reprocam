"""M9 eval report for the model judge, on the held-out failed-assertion slice (data/judge_sft_eval.jsonl).

Every number here is the model judge's own accuracy on tests that failed an assertion on the buggy build:
the only tests it sees in production. End-to-end accuracy with the rule layer (passes and crashes decided
by rules) is a different number and is never reported as the model's.

    python scripts/judge_metrics.py            # the always-REPRODUCED baseline on the current eval set
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gen_judge_data import EVAL, bucket  # noqa: E402


def _rate(pairs: list[tuple[str, str]]) -> float | None:
    return sum(p == t for t, p in pairs) / len(pairs) if pairs else None


def score(rows: list[dict], predictions: list[str]) -> dict:
    """Accuracy per eval bucket, and balanced accuracy (the mean of REPRODUCED and NOT_REPRODUCED recall,
    so a judge that always gives one answer scores 50% however the eval set is weighted)."""
    assert len(rows) == len(predictions)
    by = {}
    for r, p in zip(rows, predictions):
        by.setdefault(bucket(r), []).append((r["label"], p))
    rep = _rate(by.get("REPRODUCED", []))
    nr = _rate(by.get("NR_natural", []) + by.get("NR_mutated", []))
    return {
        "n": len(rows), "accuracy": _rate([(r["label"], p) for r, p in zip(rows, predictions)]),
        "balanced_accuracy": (rep + nr) / 2 if rep is not None and nr is not None else None,
        "reproduced_recall": rep, "natural_nr_recall": _rate(by.get("NR_natural", [])),
        "mutated_nr_recall": _rate(by.get("NR_mutated", [])),
        "counts": {b: len(v) for b, v in sorted(by.items())},
    }


def baseline(rows: list[dict]) -> dict:
    """The judge that always answers REPRODUCED."""
    return score(rows, ["REPRODUCED"] * len(rows))


def table(results: dict[str, dict]) -> str:
    """Side-by-side rows for the report, e.g. {"always REPRODUCED": baseline(rows), "Glimmer SFT": score(...)}."""
    keys = [("balanced_accuracy", "balanced accuracy"), ("accuracy", "accuracy"),
            ("reproduced_recall", "REPRODUCED rows"), ("natural_nr_recall", "natural NOT_REPRODUCED rows"),
            ("mutated_nr_recall", "mutated NOT_REPRODUCED rows")]
    pct = lambda v: "—" if v is None else f"{v:.0%}"  # noqa: E731
    head = f"{'':<30}" + "".join(f"{name:>22}" for name in results)
    return "\n".join([head] + [f"{label:<30}" + "".join(f"{pct(res[k]):>22}" for res in results.values())
                               for k, label in keys])


if __name__ == "__main__":
    eval_rows = [json.loads(line) for line in EVAL.read_text().splitlines()]
    b = baseline(eval_rows)
    print(f"eval set: {b['n']} rows · {b['counts']}")
    print(table({"always REPRODUCED": b}))
