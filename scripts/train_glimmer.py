"""M9: LoRA SFT of Muse Glimmer 30B as the model judge, on the Fireworks Serverless Training API.

    python scripts/train_glimmer.py --plan     # projected cost only, spends nothing

Data: data/judge_sft_train.jsonl and the held-out data/judge_sft_eval.jsonl (failed-assertion slice only,
built by gen_judge_data.py --split). Evaluation runs inside the training run: the eval set is sampled
(base model at step 0, then after every epoch) and scored with scripts/judge_metrics.py.

Billing (fireworks.ai/pricing, Serverless Training API row for Muse Glimmer 30B, read Oct 31 2026):
training is free for Glimmer SFT jobs until Nov 30; sampling for the eval is billed per token.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gen_judge_data import EVAL, ROWS, TRAIN  # noqa: E402

BASE_MODEL = "accounts/fireworks/models/muse-glimmer-30b"
LORA_RANK = 8
EPOCHS = 3
# USD per 1M tokens, Serverless Training API, Muse Glimmer 30B
PRICE = {"prefill": 1.96, "cached_prefill": 0.39, "sample": 4.88, "train": 5.86}
TRAINING_FREE = True  # Glimmer SFT promo, jobs started before Dec 1 (re-checked at the start of the run)
EVAL_MAX_TOKENS = 512  # the answer is ~15 tokens of JSON; the cap allows for reasoning before it
CHARS_PER_TOKEN = 3.5  # estimate for this mix of English and Python (no Glimmer tokenizer locally)
M9_CAP = 20.0


def tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def row_tokens(row: dict) -> tuple[int, int]:
    """(prompt tokens, answer tokens) of one chat row."""
    *prompt, answer = row["messages"]
    return sum(tokens(m["content"]) for m in prompt), tokens(answer["content"])


def m9_spent() -> float:
    files = [ROWS, ROWS.with_name("judge_sft_dropped.jsonl")]
    return sum(json.loads(line).get("cost_usd") or 0 for f in files if f.exists() for line in f.read_text().splitlines())


def plan(epochs: int = EPOCHS) -> dict:
    train = [json.loads(line) for line in TRAIN.read_text().splitlines()]
    ev = [json.loads(line) for line in EVAL.read_text().splitlines()]
    train_tok = sum(sum(row_tokens(r)) for r in train)
    eval_prompt = sum(row_tokens(r)[0] for r in ev)
    passes = epochs + 1  # the base model at step 0, then after each epoch
    # an eval pass prefills every eval prompt once; the shared system prompt could be cached, so this is the top
    eval_prefill = passes * eval_prompt * PRICE["prefill"] / 1e6
    eval_sample_typical = passes * len(ev) * 20 * PRICE["sample"] / 1e6
    eval_sample_max = passes * len(ev) * EVAL_MAX_TOKENS * PRICE["sample"] / 1e6
    train_cost = 0.0 if TRAINING_FREE else epochs * train_tok * PRICE["train"] / 1e6
    out = {
        "train_rows": len(train), "eval_rows": len(ev), "epochs": epochs, "eval_passes": passes,
        "train_tokens_per_epoch": train_tok, "eval_prompt_tokens_per_pass": eval_prompt,
        "train_cost": train_cost, "train_cost_without_promo": epochs * train_tok * PRICE["train"] / 1e6,
        "eval_cost_typical": eval_prefill + eval_sample_typical, "eval_cost_max": eval_prefill + eval_sample_max,
        "m9_spent": m9_spent(),
    }
    out["total_max"] = out["train_cost"] + out["eval_cost_max"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="print the projected cost and exit")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    args = ap.parse_args()
    p = plan(args.epochs)
    print(f"Muse Glimmer 30B · LoRA rank {LORA_RANK} · {p['epochs']} epochs · Serverless Training API")
    print(f"  train {p['train_rows']} rows · ~{p['train_tokens_per_epoch']:,} tokens per epoch "
          f"(estimate: {CHARS_PER_TOKEN} characters per token)")
    print(f"  training: ${p['train_cost']:.2f} (free promo; without it ${p['train_cost_without_promo']:.2f} "
          f"at ${PRICE['train']}/1M)")
    print(f"  eval inside the run: {p['eval_rows']} rows x {p['eval_passes']} passes (step 0 + each epoch) · "
          f"~{p['eval_prompt_tokens_per_pass']:,} prompt tokens per pass")
    print(f"  eval sampling: ~${p['eval_cost_typical']:.2f} typical (~20 answer tokens), ${p['eval_cost_max']:.2f} at "
          f"most ({EVAL_MAX_TOKENS} tokens each) · prefill ${PRICE['prefill']}/1M, sample ${PRICE['sample']}/1M")
    print(f"  M9 spent so far ${p['m9_spent']:.2f} · after this run at most ${p['m9_spent'] + p['total_max']:.2f} "
          f"of the ${M9_CAP:.0f} cap")
    if not args.plan:
        sys.exit("Training is not started from here yet: it waits for an explicit yes on the projection above.")


if __name__ == "__main__":
    main()
