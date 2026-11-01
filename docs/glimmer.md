# M9: Muse Glimmer 30B as the model judge

Glimmer is trained to make the one call the rule layer leaves to a model: a generated test failed an assertion
on the buggy build; did it fail for the reason the tester reported? Labels come from the buggy / known-good
oracle (`scripts/gen_judge_data.py`), never from a model.

## Settings: decided before the run

Fixed on Nov 1 2026, before any training call; `scripts/train_glimmer.py::SETTINGS` holds the same values.
Changing any of them makes a new run, recorded separately below.

| Setting | Value |
|---|---|
| Surface | Fireworks **Serverless Training API**: data is sent from the local process, no dataset upload (UI dataset uploads are disabled on the account) |
| Recipe | the fw-ai cookbook's serverless SFT notebook (`training/case-studies/sft_prompt_router/prompt_router_serverless.ipynb`), with the Glimmer settings of its starter (`training/examples/sft/muse_glimmer_starter.py`) |
| Base model | `accounts/fireworks/models/muse-glimmer-30b` (tokenizer `meta-models/Muse-Glimmer-30B`) |
| Renderer | `muse_glimmer` |
| Adapter | LoRA rank 8, alpha 32, on attention + MLP + unembedding |
| Training data | `data/glimmer_upload_train.jsonl`: 515 rows, messages only, binary instructions (below) |
| Epochs / batch size | 3 / 32 (51 optimizer steps) |
| Learning rate | 1e-4, constant (the cookbook default) |
| Optimizer | Adam β1 0.9, β2 0.999, eps 1e-8, weight decay 0, gradient clip 1.0 (the notebook's) |
| Loss | cross-entropy on the last assistant turn only: the 14–15 tokens of the verdict JSON |
| Max sequence length | 2,048; every row fits (644–1,468 tokens with the Glimmer tokenizer), none is cut |
| Shuffle seed | 0 |
| Final model | **the end-of-training checkpoint**, no checkpoint selection; saved to the account as a model |
| In-run sampling / eval | **off** (billed, and the account is paused) |

**Binary instructions**, the system prompt of every upload row and of every M9 eval (Glimmer base and tuned, and
the Muse Spark Open comparison); `scripts/judge_metrics.py::BINARY_SYSTEM`:

> You judge whether a generated Playwright test reproduced the bug a tester reported. Answer with JSON only:
> {"verdict": "REPRODUCED" | "NOT_REPRODUCED"}

The model judge only sees failed assertions, so TEST_ERROR is never its answer (the rule layer decides it). The
deployed product judge (`backend/judge.py`) keeps its own prompt and is unchanged.
`python scripts/gen_judge_data.py --export-binary` rebuilds both upload files from the split, byte for byte.

## Data

From the failed-assertion slice only, group-aware, seed 1031 (`gen_judge_data.py --split`):

| | rows | REPRODUCED | NOT_REPRODUCED (natural) | NOT_REPRODUCED (mutated) |
|---|---|---|---|---|
| train (`glimmer_upload_train.jsonl`) | 515 | 329 | 64 | 122 |
| eval, held out (`glimmer_upload_eval.jsonl`) | 40 | 20 | 10 | 10 |

At most one mutated row per group in train. Eval rows are in the same order as `judge_sft_eval.jsonl`, which
carries their variant and label.

## Commands

```bash
bash scripts/setup_fw_cookbook.sh            # once: cookbook + environment in ../fw-cookbook (outside the repo)
FW=../fw-cookbook/cookbook/training/.venv/bin/python
$FW scripts/train_glimmer.py plan            # settings, data check, cost; no API calls
$FW scripts/train_glimmer.py train           # train -> save the adapter; no sampling (free under the promotion)
$FW scripts/train_glimmer.py eval --yes      # BILLED, separately approved: base + tuned on the 40 eval rows
python scripts/eval_muse_judge.py --yes      # BILLED: Muse Spark Open on the same 40 rows, same instructions
```

Projected (`plan`, token counts from the Glimmer tokenizer): training $0 under the promotion (LoRA SFT jobs
started before Dec 1 2026; $7.92 otherwise at $5.86/1M); eval sampling ~$0.15, at most $0.34 (40 rows × base and
tuned, 512 answer tokens cap); M9 total at most $4.05 of the $20 cap.

**The eval report has two numbers, never mixed:** the model judge's accuracy on the held-out failed-assertion
slice (Glimmer's accuracy: balanced accuracy, accuracy, and recall on REPRODUCED / natural NOT_REPRODUCED /
mutated NOT_REPRODUCED rows, next to the always-REPRODUCED baseline at 50% balanced), and end-to-end accuracy
with the rule layer on the held-out groups, which includes rows the model never sees and is not Glimmer's
accuracy.

Not verified yet (the account is suspended): that `eval` can sample the run's saved sampler checkpoint from a
new session. If it can't, `eval` rebuilds the adapter from the saved training state
(`create_training_client_from_state`) and samples that.

## Environment

The cookbook lives outside the repo in `../fw-cookbook` (cookbook commit `57968a2`, Oct 21 2026), built by
`scripts/setup_fw_cookbook.sh`. **torch substitution:** the cookbook pins torch ≥ 2.13, which has no wheel for
Intel Macs; on this machine (macOS x86_64) the script installs **torch 2.2.2** and the cookbook with `--no-deps`,
then its other dependencies (plus `protobuf` and `pyqwest`, which the training SDK imports). The renderer uses
torch only to build per-token weight tensors; no model runs locally.

## Run log
- Nov 1 2026, minimal call before any run: `create_lora_training_client(base_model=muse-glimmer-30b, rank=8, alpha=32)`
  refused, nothing created or trained:
  `fireworks.training.sdk._core._exceptions.APIStatusError: Error code: 412 - {'error': {'message': 'Account admin-l1mezhv2y3bx is suspended, possibly due to reaching the monthly spending limit or failure to pay past invoices. Please go to https://fireworks.ai/account/billing for more information.', 'param': None, 'code': 'PRECONDITION_FAILED', 'type': 'error'}, 'request_id': 'c9425896-2b42-4799-a4d4-46e6b475283d'}`
