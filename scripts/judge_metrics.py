"""M9 eval report for the model judge, on the held-out failed-assertion slice (data/judge_sft_eval.jsonl).

Every number here is the model judge's own accuracy on tests that failed an assertion on the buggy build:
the only tests it sees in production. End-to-end accuracy with the rule layer (passes and crashes decided
by rules) is a different number and is never reported as the model's.

    python scripts/judge_metrics.py            # the always-REPRODUCED baseline on the current eval set
"""
import json
from pathlib import Path

# Standard library only: this module also runs in the fw-cookbook environment (scripts/train_glimmer.py).
ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "data" / "judge_sft_eval.jsonl"     # the held-out slice, with variant/label metadata
TRAIN = ROOT / "data" / "judge_sft_train.jsonl"
ALL = ROOT / "data" / "judge_data_all.jsonl"
UPLOAD_TRAIN = ROOT / "data" / "glimmer_upload_train.jsonl"  # messages only, binary instructions
UPLOAD_EVAL = ROOT / "data" / "glimmer_upload_eval.jsonl"

# The model judge only sees tests that failed an assertion, so its only answers are these two (TEST_ERROR is
# decided by the rule layer). Glimmer is trained on these instructions, and every M9 eval (Glimmer base and
# tuned, and the Muse Spark Open comparison) uses them word for word. The deployed product judge keeps its own.
BINARY_SYSTEM = ('You judge whether a generated Playwright test reproduced the bug a tester reported. '
                 'Answer with JSON only: {"verdict": "REPRODUCED" | "NOT_REPRODUCED"}')
VERDICTS = ("REPRODUCED", "NOT_REPRODUCED")


def is_mutated(row: dict) -> bool:
    """Broken by code (mut_*), as opposed to written by the model ("natural")."""
    return row["variant"].startswith("mut_")


def bucket(row: dict) -> str:
    """Eval bucket: REPRODUCED, or NOT_REPRODUCED split by where the test came from."""
    if row["label"] == "REPRODUCED":
        return "REPRODUCED"
    return "NR_mutated" if is_mutated(row) else "NR_natural"


def binary_messages(row: dict) -> list[dict]:
    """A split row's chat with the binary instructions in place of its system prompt."""
    return [{"role": "system", "content": BINARY_SYSTEM}] + row["messages"][1:]


def write_upload_files() -> None:
    """data/glimmer_upload_{train,eval}.jsonl from the split: messages only, binary instructions."""
    for src, dst in ((TRAIN, UPLOAD_TRAIN), (EVAL, UPLOAD_EVAL)):
        rows = [json.loads(line) for line in src.read_text().splitlines()]
        dst.write_text("".join(json.dumps({"messages": binary_messages(r)}, ensure_ascii=False) + "\n" for r in rows))


def parse_verdict(text: str) -> str:
    """The verdict in a model answer, or "INVALID" (counted wrong) when there is none."""
    start, end = (text or "").find("{"), (text or "").rfind("}")
    try:
        v = json.loads(text[start:end + 1]).get("verdict") if start != -1 and end > start else None
    except (ValueError, AttributeError):
        v = None
    return v if v in VERDICTS else "INVALID"


def load_eval() -> tuple[list[dict], list[dict]]:
    """(eval rows with metadata, the same rows as binary chats), checked to be the same rows in the same order."""
    meta = [json.loads(line) for line in EVAL.read_text().splitlines()]
    chats = [json.loads(line) for line in UPLOAD_EVAL.read_text().splitlines()]
    assert len(meta) == len(chats) and all(c["messages"] == binary_messages(m) for m, c in zip(meta, chats)), \
        "glimmer_upload_eval.jsonl does not match judge_sft_eval.jsonl: rebuild it (gen_judge_data.py --export-binary)"
    return meta, chats


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


def end_to_end(eval_rows: list[dict], predictions: list[str], all_rows: list[dict]) -> dict:
    """The whole judge on the held-out groups: the rule layer decides the rows that passed or crashed on the buggy
    build (pass -> NOT_REPRODUCED, error -> TEST_ERROR, which match the oracle label by construction), the model
    decides the failed-assertion rows. Includes rows the model never sees, so it is NOT the model's accuracy."""
    groups = {r.get("group") for r in eval_rows}
    rule_rows = [r for r in all_rows if r.get("group") in groups and r.get("label")
                 and r["oracle"]["buggy"] != "assert_fail"]
    rule = {"pass": "NOT_REPRODUCED", "error": "TEST_ERROR"}
    rule_ok = sum(rule[r["oracle"]["buggy"]] == r["label"] for r in rule_rows)
    model_ok = sum(p == r["label"] for r, p in zip(eval_rows, predictions))
    n = len(rule_rows) + len(eval_rows)
    return {"n": n, "rule_rows": len(rule_rows), "model_rows": len(eval_rows),
            "accuracy": (rule_ok + model_ok) / n if n else None}


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
    eval_rows, _ = load_eval()
    b = baseline(eval_rows)
    print(f"eval set: {b['n']} rows · {b['counts']}")
    print(table({"always REPRODUCED": b}))
