"""M9 comparison: Muse Spark Open as the model judge on the same 40 held-out rows, with the same binary
instructions Glimmer is trained and evaluated on (judge_metrics.BINARY_SYSTEM, from the upload file).
The deployed product judge (backend/judge.py) is not used or changed here.

    python scripts/eval_muse_judge.py                  # projected cost only
    python scripts/eval_muse_judge.py --yes            # BILLED: 40 calls on LLM_PROVIDER (or --provider)

Writes data/glimmer/muse-<provider>-<time>/predictions.jsonl + eval.json, scored like Glimmer's eval.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.llm import chat  # noqa: E402
from judge_metrics import ALL, VERDICTS, baseline, end_to_end, load_eval, parse_verdict, score, table  # noqa: E402

# The binary answer, enforced the same way the product judge enforces its schema
SCHEMA = {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["verdict"],
    "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}}}}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, help="default: LLM_PROVIDER")
    ap.add_argument("--yes", action="store_true", help="approve the billed calls")
    args = ap.parse_args()
    provider = (args.provider or os.getenv("LLM_PROVIDER", "meta")).lower()
    eval_meta, chats = load_eval()
    prompt_tok = sum(len(m["content"]) for c in chats for m in c["messages"][:-1]) / 3.5  # estimate
    p_in, p_out = os.getenv(f"PRICE_{provider.upper()}_IN"), os.getenv(f"PRICE_{provider.upper()}_OUT")
    if p_in and p_out:  # ~400 output tokens per call at low effort (reasoning included), from the judge log
        print(f"{len(chats)} calls on {provider} · ~${(prompt_tok * float(p_in) + len(chats) * 400 * float(p_out)) / 1e6:.2f}")
    else:
        print(f"{len(chats)} calls on {provider} · no PRICE_{provider.upper()}_IN/_OUT set, cost not estimated")
    if not args.yes:
        sys.exit("Billed: re-run with --yes once it is approved.")

    run_dir = ROOT / "data" / "glimmer" / f"muse-{provider}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True)
    preds, cost = [], 0.0
    with (run_dir / "predictions.jsonl").open("w") as f:
        for i, c in enumerate(chats):
            try:
                text, meta = chat(c["messages"][:-1], stage="judge", provider=provider, response_format=SCHEMA,
                                  log_extra={"prompt_version": "m9 binary eval"})
            except Exception as e:  # noqa: BLE001  (a failed call is a wrong answer, and is recorded)
                text, meta = "", {"error": f"{e.__class__.__name__}: {e}"}
            preds.append(parse_verdict(text))
            cost += meta.get("cost_usd") or 0
            f.write(json.dumps({"index": i, "prediction": preds[-1], "answer_text": text[:2000],
                                "error": meta.get("error"), "model": meta.get("model")}) + "\n")
            print(f"  {i + 1}/{len(chats)} {preds[-1]}", flush=True)
    all_rows = [json.loads(line) for line in ALL.read_text().splitlines()]
    report = {"model_judge_on_held_out_slice": {"always REPRODUCED": baseline(eval_meta),
                                                f"Muse Spark Open ({provider})": score(eval_meta, preds)},
              "end_to_end_with_rule_layer": end_to_end(eval_meta, preds, all_rows),  # NOT the model's accuracy
              "provider": provider, "cost_usd": round(cost, 4)}
    (run_dir / "eval.json").write_text(json.dumps(report, indent=2))
    print(table(report["model_judge_on_held_out_slice"]))
    e2e = report["end_to_end_with_rule_layer"]
    print(f"End-to-end with the rule layer ({e2e['n']} rows, {e2e['rule_rows']} by rules), not the model's accuracy: "
          f"{e2e['accuracy']:.0%} · cost ${cost:.3f}")


if __name__ == "__main__":
    main()
