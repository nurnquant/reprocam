# Preflight results — Sat Oct 31, 2026

One run per cell on a short reasoning question ("17 sheep" puzzle; correct answer 36), plus a
64 px solid-red PNG for image input. Single samples: treat token counts as indicative, not exact.

| Provider | Model id | none | minimal | low | medium | high | Image in |
|---|---|---|---|---|---|---|---|
| Meta Model API | `muse-spark-1.3` | rejected (400) | 151 | 454 | 535 | 500 | OK ("red") |
| Baseten | `meta-models/muse-spark-open` | 132* | 139 | 164 | 477 | 337 | OK ("Red") |
| Fireworks | `accounts/fireworks/models/muse-spark-open` | rejected (400) | 159 | 220 | 392 | 588 | OK ("Red") |

Reasoning tokens shown; every accepted call answered correctly (36).

\* Baseten accepts `none` but still reasons (~130 tokens): it is probably mapped to a minimum
level, not truly off. Don't rely on `none` meaning "no reasoning".

## Findings
- **Effort is applied on all three providers**: token use clearly changes between levels.
- **Fireworks (rechecked Oct 31, new key)** is the only provider where tokens rise steadily
  minimal → high (159 → 220 → 392 → 588), and it rejects `none` like Meta (400: reasoning can't be disabled).
- **Levels are not comparable across providers**: Baseten `low` (164) ≈ Meta `minimal` (151);
  Meta `low` (454) ≈ Baseten `medium` (477). Run the M4b sweep per provider; never assume
  "low" means the same thing on both.
- **Non-monotonic at the top** on Meta and Baseten (high < medium on one sample). M4b's 3 repeats per cell decide.
- **Image input works on all three**, so `understand.py` (keyframes → steps) can run on Muse Spark Open
  via Baseten or Fireworks, not just on Meta's API.
- Baseten id from the hackathon guide (`meta-models/muse-spark-open-1026`) returns **404**;
  `meta-models/muse-spark-open` works (listed by `GET /v1/models`).

## Decisions
- Default `LLM_PROVIDER=fireworks` (open-weight bonus) for understand, testgen, judge: matches the
  model map, same provider as the M9 Glimmer judge, and the cleanest effort scaling. Baseten is the
  open-weight fallback (one line in `.env`).
- Meta Model API stays required for Voice Transcribe and SAM 3.1, and is the fallback for text stages.
- M4b sweep: Fireworks {low, medium, high} × 3 samples × 3 repeats; Baseten next if time allows.
