"""M9: LoRA SFT of Muse Glimmer 30B as the model judge, on the Fireworks Serverless Training API.

The loop follows the fw-ai cookbook's serverless SFT notebook
(training/case-studies/sft_prompt_router/prompt_router_serverless.ipynb) with the Glimmer settings of its
starter (training/examples/sft/muse_glimmer_starter.py). Data goes from this process to the API; nothing is
uploaded as a dataset. Settings were decided before the run: SETTINGS below = docs/glimmer.md.

Run from the reprocam folder with the fw-cookbook Python (bash scripts/setup_fw_cookbook.sh prints it):
    FW=../fw-cookbook/cookbook/training/.venv/bin/python
    $FW scripts/train_glimmer.py plan            # settings, data check, projected cost; no API calls
    $FW scripts/train_glimmer.py train           # train -> save the adapter to the account. No sampling:
                                                 # training is free under the promotion, nothing else is billed
    $FW scripts/train_glimmer.py eval --yes      # BILLED sampling, only after approval: base and tuned Glimmer
                                                 # on the 40 held-out rows (scripts/eval_muse_judge.py runs
                                                 # the Muse Spark Open comparison on the same rows)

Each run writes data/glimmer/<run_id>/: manifest.json (settings, session, checkpoints, promoted model),
metrics.jsonl (loss per step), and after eval predictions_{base,tuned}.jsonl + eval.json. The run id,
session id and start time are added to docs/glimmer.md before the first training step.
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from judge_metrics import (ALL, BINARY_SYSTEM, UPLOAD_TRAIN, baseline, end_to_end, load_eval,  # noqa: E402
                           parse_verdict, score, table)

DOC = ROOT / "docs" / "glimmer.md"
OUT = ROOT / "data" / "glimmer"

# Decided before the run (docs/glimmer.md). Changing any of these means a new, separately recorded run.
SETTINGS = {
    "surface": "Fireworks Serverless Training API",
    "base_model": "accounts/fireworks/models/muse-glimmer-30b",
    "tokenizer": "meta-models/Muse-Glimmer-30B",
    "renderer": "muse_glimmer",
    "train_file": "data/glimmer_upload_train.jsonl",
    "train_rows": 515,
    "lora_rank": 8,
    "lora_alpha": 32,
    "train_attn": True, "train_mlp": True, "train_unembed": True,
    "epochs": 3,
    "batch_size": 32,
    "learning_rate": 1e-4,
    "adam": {"beta1": 0.9, "beta2": 0.999, "eps": 1e-8, "weight_decay": 0.0, "grad_clip_norm": 1.0},
    "loss": "cross_entropy on the last assistant turn (the verdict JSON) only",
    "max_seq_len": 2048,
    "shuffle_seed": 0,
    "final_model": "the end-of-training checkpoint (no checkpoint selection)",
    "in_run_sampling": False,
}
# Serverless Training API, Muse Glimmer 30B, USD per 1M tokens (fireworks.ai/pricing, read Oct 31 2026)
PRICE = {"prefill": 1.96, "sample": 4.88, "train": 5.86}
PROMOTION_END = datetime(2026, 12, 1, tzinfo=timezone(timedelta(hours=-8)))  # LoRA SFT free before this
EVAL_MAX_TOKENS = 512  # the answer is ~15 tokens of JSON; the cap leaves room for any reasoning before it
M9_CAP = 20.0
API_BASE = "https://api.fireworks.ai"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _check_train_rows() -> list[dict]:
    rows = _rows(UPLOAD_TRAIN)
    bad = [i for i, r in enumerate(rows) if [m["role"] for m in r["messages"]] != ["system", "user", "assistant"]
           or r["messages"][0]["content"] != BINARY_SYSTEM or parse_verdict(r["messages"][-1]["content"]) == "INVALID"]
    if len(rows) != SETTINGS["train_rows"] or bad:
        sys.exit(f"{UPLOAD_TRAIN.name}: {len(rows)} rows (expected {SETTINGS['train_rows']}), "
                 f"{len(bad)} not system/user/assistant with the binary instructions and a verdict: {bad[:10]}")
    return rows


def _renderer():
    from training.renderer import get_renderer
    from training.renderer.tokenizer import get_tokenizer
    tokenizer = get_tokenizer(SETTINGS["tokenizer"])
    return tokenizer, get_renderer(SETTINGS["renderer"], tokenizer)


def _datums(rows: list[dict], renderer) -> list:
    """Each chat -> a shifted next-token datum that trains on the verdict only (as in the notebook)."""
    from fireworks.training import sdk
    from training.renderer import TrainOnWhat
    out, oversized = [], []
    for i, ex in enumerate(rows):
        model_input, weights = renderer.build_supervised_example(ex["messages"],
                                                                 train_on_what=TrainOnWhat.LAST_ASSISTANT_TURN)
        tokens = [int(t) for t in model_input.to_ints()]
        w = [float(x) for x in weights.tolist()]
        if len(tokens) > SETTINGS["max_seq_len"]:
            oversized.append(i)
            continue
        out.append(sdk.Datum(model_input=sdk.ModelInput.from_ints(tokens[:-1]),
                             loss_fn_inputs={"target_tokens": tokens[1:], "weights": w[1:]}))
    if oversized:  # never truncated silently: a cut row would train on a different input
        sys.exit(f"{len(oversized)} rows exceed max_seq_len {SETTINGS['max_seq_len']}: {oversized[:20]}")
    return out


def _service():
    from fireworks.training.sdk import FiretitanServiceClient
    from training.utils.serverless import enable_serverless_supervised_409_retry, serverless_base_url
    if not os.environ.get("FIREWORKS_API_KEY"):
        from dotenv import dotenv_values
        os.environ["FIREWORKS_API_KEY"] = dotenv_values(ROOT / ".env").get("FIREWORKS_API_KEY") or ""
    if not os.environ["FIREWORKS_API_KEY"]:
        sys.exit("FIREWORKS_API_KEY is not set (environment or .env).")
    service = FiretitanServiceClient(api_key=os.environ["FIREWORKS_API_KEY"], base_url=serverless_base_url(API_BASE))
    enable_serverless_supervised_409_retry(service)
    return service


def _lora_client(service):
    return service.create_lora_training_client(
        base_model=SETTINGS["base_model"], rank=SETTINGS["lora_rank"], alpha=SETTINGS["lora_alpha"],
        train_attn=SETTINGS["train_attn"], train_mlp=SETTINGS["train_mlp"], train_unembed=SETTINGS["train_unembed"])


def _account() -> str:
    if os.environ.get("FIREWORKS_ACCOUNT_ID"):
        return os.environ["FIREWORKS_ACCOUNT_ID"]
    from fireworks import Fireworks
    first = next(iter(Fireworks().accounts.list(page_size=1)), None)
    if first is None:
        sys.exit("Could not resolve the Fireworks account for this key; set FIREWORKS_ACCOUNT_ID.")
    return first.name.split("/")[-1]


def _log_to_doc(line: str) -> None:
    """Append one line to the run log, the last section of docs/glimmer.md (before training starts, then on the
    outcome)."""
    text = DOC.read_text()
    if "\n## Run log" not in text:
        sys.exit(f"{DOC} has no '## Run log' section")
    DOC.write_text(text.rstrip("\n") + f"\n{line}\n")


def _save(manifest: dict, run_dir: Path) -> None:
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def plan() -> dict:
    """Settings, data check and the projected cost of train (free) and of the separate billed eval."""
    rows = _check_train_rows()
    eval_meta, eval_chats = load_eval()
    try:  # real token counts in the fw-cookbook environment; an estimate elsewhere
        from training.renderer import TrainOnWhat
        _, renderer = _renderer()
        train_tok = sum(len(renderer.build_supervised_example(r["messages"], train_on_what=TrainOnWhat.LAST_ASSISTANT_TURN)
                            [0].to_ints()) for r in rows)
        eval_tok = sum(len(renderer.build_generation_prompt(c["messages"][:-1]).to_ints()) for c in eval_chats)
        how = "counted with the Glimmer tokenizer"
    except ImportError:
        train_tok = round(sum(len(m["content"]) for r in rows for m in r["messages"]) / 3.5)
        eval_tok = round(sum(len(m["content"]) for c in eval_chats for m in c["messages"][:-1]) / 3.5)
        how = "estimated at 3.5 characters per token (run with the fw-cookbook Python for exact counts)"
    free = datetime.now(timezone.utc) < PROMOTION_END
    steps = SETTINGS["epochs"] * -(-len(rows) // SETTINGS["batch_size"])
    eval_cost_max = 2 * (eval_tok * PRICE["prefill"] + len(eval_chats) * EVAL_MAX_TOKENS * PRICE["sample"]) / 1e6
    eval_cost_typ = 2 * (eval_tok * PRICE["prefill"] + len(eval_chats) * 20 * PRICE["sample"]) / 1e6
    return {"rows": len(rows), "steps": steps, "train_tokens_per_epoch": train_tok, "eval_prompt_tokens": eval_tok,
            "tokens": how, "training_free": free,
            "train_cost": 0.0 if free else SETTINGS["epochs"] * train_tok * PRICE["train"] / 1e6,
            "train_cost_without_promo": SETTINGS["epochs"] * train_tok * PRICE["train"] / 1e6,
            "eval_cost_typical": eval_cost_typ, "eval_cost_max": eval_cost_max, "eval_rows": len(eval_chats),
            "m9_spent": m9_spent()}


def m9_spent() -> float:
    """USD spent on M9 so far: the model calls that generated the judge data."""
    rows = ROOT / "data" / "judge_sft_rows.jsonl"
    return sum(json.loads(line).get("cost_usd") or 0 for line in rows.read_text().splitlines()) if rows.exists() else 0.0


def print_plan(p: dict) -> None:
    print("Settings (decided before the run, docs/glimmer.md):")
    for k, v in SETTINGS.items():
        print(f"  {k}: {v}")
    print(f"\ntrain: {p['rows']} rows · {p['steps']} optimizer steps · ~{p['train_tokens_per_epoch']:,} tokens per "
          f"epoch ({p['tokens']})")
    print(f"  cost: ${p['train_cost']:.2f} ({'free under the Glimmer SFT promotion' if p['training_free'] else 'promotion over'}; "
          f"${p['train_cost_without_promo']:.2f} at ${PRICE['train']}/1M otherwise) · no sampling")
    print(f"eval (separate, billed, needs --yes): {p['eval_rows']} rows x 2 (base, tuned) · "
          f"~{p['eval_prompt_tokens']:,} prompt tokens per pass · ~${p['eval_cost_typical']:.2f} typical, "
          f"${p['eval_cost_max']:.2f} at most ({EVAL_MAX_TOKENS} answer tokens each)")
    print(f"M9 spent so far ${p['m9_spent']:.2f} · with train + eval at most "
          f"${p['m9_spent'] + p['train_cost'] + p['eval_cost_max']:.2f} of the ${M9_CAP:.0f} cap")


def train(args) -> int:
    if datetime.now(timezone.utc) >= PROMOTION_END and not args.allow_paid:
        sys.exit("The Glimmer SFT promotion has ended: training is billed now. Re-run with --allow-paid after approval.")
    from fireworks.training import sdk
    from fireworks.training.sdk import FireworksClient
    rows = _check_train_rows()
    _, renderer = _renderer()
    datums = _datums(rows, renderer)
    run_id = args.run_id or "glimmer-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"run_id": run_id, "settings": SETTINGS, "rows": len(rows), "datums": len(datums)}
    print(f"run {run_id}: {len(datums)} datums, {SETTINGS['epochs']} epochs, batch {SETTINGS['batch_size']}", flush=True)

    service = _service()
    try:
        try:
            training_client = _lora_client(service)
        except Exception as e:  # e.g. 412 account suspended: recorded, nothing trained
            manifest.update(state="refused", error=f"{e.__class__.__name__}: {e}")
            _save(manifest, run_dir)
            _log_to_doc(f"- {run_id}: session refused before training · `{manifest['error'][:300]}`")
            raise
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest.update(state="training", started=started, session=getattr(service, "training_session_id", None),
                        session_name=getattr(service, "training_session_name", None),
                        trainer_run=getattr(training_client, "run_id", None))
        _save(manifest, run_dir)
        _log_to_doc(f"- {run_id}: started {started} · session `{manifest['session']}` · training run "
                    f"`{manifest['trainer_run']}` · settings as above")

        adam = sdk.AdamParams(learning_rate=SETTINGS["learning_rate"], **SETTINGS["adam"])
        rng, step = random.Random(SETTINGS["shuffle_seed"]), 0
        with (run_dir / "metrics.jsonl").open("a") as log:
            for epoch in range(SETTINGS["epochs"]):
                order = list(range(len(datums)))
                rng.shuffle(order)
                for start in range(0, len(order), SETTINGS["batch_size"]):
                    batch = [datums[i] for i in order[start:start + SETTINGS["batch_size"]]]
                    fb = training_client.forward_backward(batch, "cross_entropy").result()
                    opt = training_client.optim_step(adam, emit_grad_norm_metrics=True).result()
                    step += 1
                    m = dict(getattr(fb, "metrics", None) or {})
                    tokens = m.get("response_tokens") or m.get("num_loss_tokens") or 1.0
                    row = {"step": step, "epoch": epoch + 1, "batch": len(batch),
                           "loss": round(m.get("loss:sum", 0.0) / max(float(tokens), 1.0), 5),
                           **{k: v for k, v in (getattr(opt, "metrics", None) or {}).items() if "grad" in k}}
                    log.write(json.dumps(row) + "\n")
                    log.flush()
                    print(json.dumps(row), flush=True)
        manifest.update(steps=step, final_loss=row["loss"])

        # The final model is the end-of-training checkpoint: a resumable state and a sampler checkpoint,
        # then the sampler checkpoint is promoted to a model on the account (outlives the session).
        manifest["state_path"] = training_client.save_state("glimmer-final-state").result().path
        manifest["sampler_path"] = training_client.save_weights_for_sampler("glimmer-final").result().path
        _save(manifest, run_dir)
        account = _account()
        fw = FireworksClient(api_key=os.environ["FIREWORKS_API_KEY"], base_url=API_BASE)
        ckpts = [c for c in fw.list_training_session_checkpoints(service.training_session_name)
                 if c.get("promotable") and "glimmer-final" in (c.get("checkpointName") or c.get("name") or "")]
        if not ckpts:
            manifest.update(state="trained, not promoted", promoted_model=None)
            print("no promotable final checkpoint listed: the adapter stays session-only", flush=True)
        else:
            target = max(ckpts, key=lambda c: c.get("createTime", ""))
            model_id = f"reprocam-judge-{run_id}"[:63].rstrip("-")
            fw.promote_session_checkpoint(name=target["name"], output_model_id=model_id,
                                          base_model=SETTINGS["base_model"])
            manifest.update(state="trained and saved", promoted_model=f"accounts/{account}/models/{model_id}",
                            promoted_from=target["name"])
        manifest["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(manifest, run_dir)
        _log_to_doc(f"- {run_id}: {manifest['state']} {manifest['finished']} · {step} steps · final train loss "
                    f"{manifest['final_loss']} · adapter `{manifest.get('promoted_model')}`")
        print(json.dumps(manifest, indent=2))
    finally:
        service.close()
    return 0


def _sample_all(service, model_path: str, chats: list[dict], tokenizer, renderer, label: str, run_dir: Path) -> dict:
    from fireworks.training import sdk
    from training.renderer import get_text_content
    sampler = service.create_sampling_client(model_path=model_path, tokenizer=tokenizer)
    params = sdk.SamplingParams(max_tokens=EVAL_MAX_TOKENS, temperature=0.0, stop=renderer.get_stop_sequences())
    preds, prompt_tok, sampled_tok, unterminated = [], 0, 0, 0
    try:
        prompts = [renderer.build_generation_prompt(c["messages"][:-1]) for c in chats]  # binary instructions
        futures = [sampler.sample(prompt=p, num_samples=1, sampling_params=params) for p in prompts]
        with (run_dir / f"predictions_{label}.jsonl").open("w") as f:
            for i, (prompt, fut) in enumerate(zip(prompts, futures)):
                res = fut.result() if hasattr(fut, "result") else fut
                out = list(res.sequences[0].tokens)
                msg, termination = renderer.parse_response(out)
                text = get_text_content(msg)
                prompt_tok += len(prompt.to_ints())
                sampled_tok += len(out)
                unterminated += not termination.is_clean
                preds.append(parse_verdict(text))
                f.write(json.dumps({"index": i, "prediction": preds[-1], "answer_text": text[:2000],
                                    "truncated": not termination.is_clean}) + "\n")
    finally:
        getattr(sampler, "close", lambda: None)()
    cost = (prompt_tok * PRICE["prefill"] + sampled_tok * PRICE["sample"]) / 1e6
    return {"predictions": preds, "prompt_tokens": prompt_tok, "sampled_tokens": sampled_tok,
            "unterminated": unterminated, "cost_usd": round(cost, 4)}


def evaluate(args) -> int:
    """BILLED: sample base and tuned Glimmer on the held-out rows and score them (judge_metrics)."""
    p = plan()
    print(f"eval: {p['eval_rows']} rows x 2 · ~${p['eval_cost_typical']:.2f} typical, ${p['eval_cost_max']:.2f} at most")
    if not args.yes:
        sys.exit("Sampling is billed: re-run with --yes once it is approved.")
    run_dir = OUT / args.run_id if args.run_id else max((d for d in OUT.iterdir() if (d / "manifest.json").exists()),
                                                        key=lambda d: d.name)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if not manifest.get("sampler_path") and not manifest.get("state_path"):
        sys.exit(f"{run_dir.name} has no saved checkpoint ({manifest.get('state')})")
    eval_meta, chats = load_eval()
    tokenizer, renderer = _renderer()
    service = _service()
    try:
        # base = a fresh, untrained LoRA (zero update): Glimmer itself, sampled the same way as tuned
        base_path = _lora_client(service).save_weights_for_sampler("eval-base").result().path
        base = _sample_all(service, base_path, chats, tokenizer, renderer, "base", run_dir)
        try:  # the run's sampler checkpoint; if another session can't read it, rebuild it from the saved state
            tuned = _sample_all(service, manifest["sampler_path"], chats, tokenizer, renderer, "tuned", run_dir)
        except Exception as e:  # noqa: BLE001
            print(f"sampler checkpoint not usable here ({e.__class__.__name__}: {str(e)[:200]}); loading the state",
                  flush=True)
            restored = service.create_training_client_from_state(manifest["state_path"])
            path = restored.save_weights_for_sampler("eval-tuned").result().path
            tuned = _sample_all(service, path, chats, tokenizer, renderer, "tuned", run_dir)
    finally:
        service.close()
    all_rows = _rows(ALL)
    report = {
        "model_judge_on_held_out_slice": {  # the model judge's own accuracy: failed-assertion rows only
            "always REPRODUCED": baseline(eval_meta),
            "Glimmer base": score(eval_meta, base["predictions"]),
            "Glimmer tuned": score(eval_meta, tuned["predictions"]),
        },
        # rule layer + model on the held-out groups: NOT Glimmer's accuracy
        "end_to_end_with_rule_layer": {"Glimmer base": end_to_end(eval_meta, base["predictions"], all_rows),
                                       "Glimmer tuned": end_to_end(eval_meta, tuned["predictions"], all_rows)},
        "sampling": {k: {x: v[x] for x in ("prompt_tokens", "sampled_tokens", "unterminated", "cost_usd")}
                     for k, v in (("base", base), ("tuned", tuned))},
    }
    (run_dir / "eval.json").write_text(json.dumps(report, indent=2))
    print("Model judge on the held-out failed-assertion slice (Glimmer's accuracy):")
    print(table(report["model_judge_on_held_out_slice"]))
    e2e = report["end_to_end_with_rule_layer"]
    print(f"\nEnd-to-end judge with the rule layer, held-out groups ({e2e['Glimmer tuned']['n']} rows, "
          f"{e2e['Glimmer tuned']['rule_rows']} decided by rules) — not Glimmer's accuracy: "
          f"base {e2e['Glimmer base']['accuracy']:.0%}, tuned {e2e['Glimmer tuned']['accuracy']:.0%}")
    print(f"sampling cost: ${base['cost_usd'] + tuned['cost_usd']:.3f}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    t = sub.add_parser("train")
    t.add_argument("--run-id", default=None)
    t.add_argument("--allow-paid", action="store_true", help="train after the promotion ends (billed)")
    e = sub.add_parser("eval")
    e.add_argument("--run-id", default=None, help="default: the latest run in data/glimmer/")
    e.add_argument("--yes", action="store_true", help="approve the billed sampling")
    args = ap.parse_args()
    if args.command == "plan":
        print_plan(plan())
        return 0
    return train(args) if args.command == "train" else evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
