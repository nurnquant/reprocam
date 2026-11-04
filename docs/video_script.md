# ReproCam demo video: 3:00 script (draft 2)

For: the hackathon judges. Screen recording of the site plus a short phone clip; voice-over recorded
separately. Every failure line, verdict and number below is copied from a real run (`samples/bug2/`,
`samples/bug1/`, `data/effort_sweep.jsonl`, `docs/understand_stability.md`); none is staged or edited.

**Before recording**
- Cached replays (`/?sample=bug2`, `/?sample=bug1`) at 2× speed cost $0 and always look the same. They were
  recorded on Fireworks, so their badges say Fireworks: don't name a provider over them.
- The live segment is a real upload on the deployed site via the owner link (bug1). Its badges say Muse Spark ·
  Meta Model API for understanding and Muse Spark Open · Baseten for the test and the judge. The last check took
  65 s, so at 4× it runs ~16 s: keep upload → timeline → verdict with two jump cuts to fit 8 s, and keep the
  "4×" label true to the factor actually used.
- The phone clip is the bug2 recording itself (`samples/bug2.mov`), or a re-film of the same steps.
- The Glimmer segment (2:17–2:32) goes in only if M9 has an eval result. Without one, cut it and give the 15 s
  to the architecture shot (alternate timings in brackets).

| Time | Shot | On-screen caption | Narration |
|---|---|---|---|
| 0:00–0:14 | Phone clip of the bug2 recording, from the first frame: Pebble Night Light in the basket, tester taps "−" at quantity 1, the badge reads 0, the checkout still says $18.50. No title card. | 0:00–0:06: **Everything shown was built during this hackathon.** · 0:06–0:14: A tester's bug recording, with narration | "A tester finds a bug and records it: the basket says zero items, but checkout still charges eighteen fifty. Normally that becomes a ticket someone has to reproduce by hand." |
| 0:14–0:21 | **You**, on camera or as voice-over over the phone clip's last frame (5–8 s). | Your name and role (lower third) | *Placeholder, you write the final line:* "I'm a senior SDET… this is the tool I wanted." |
| 0:21–0:33 | Site home, then the bug2 sample replay at 2×. The timeline lights up: frames, Voice Transcribe, understanding, each with its model · provider · effort badge. | Cached replay of a real run · $0 | "ReproCam takes the recording. Voice Transcribe turns the narration into text, and Muse Spark models read the keyframes and the transcript." |
| 0:33–0:45 | Zoom in on the card "What the agent understood": 4 steps (product page, View basket, "−", Checkout) and the claim. | Steps use only element ids from the store's map | "It writes down the steps and what the tester claims is wrong, using only element ids that exist in the app." |
| 0:45–1:00 | Attempt 1, trimmed: the red run line, then the known-good check failing. Hold on the known-good line. | Over 0:45–1:16: **Understanding isn't perfect (6/9 on our bugs); that's why ReproCam proves every bug before filing it.** · lower line: on the known-good build `basket badge should show 0 after removing only item · Expected value: '0' · Actual value: 1` | "Its first test fails on the buggy build. But ReproCam runs the same test on a known-good build too, and it fails there as well. So the test was wrong, and the agent tries again." |
| 1:00–1:16 | Attempt 2: red on buggy, then "passes on fixed build" turns green. Status pill: REPRODUCED · verified. | (retry caption continues) · lower line: `checkout total should be $0.00 when basket is empty · Actual value: $18.50` · passes on the known-good build | "The second test fails on the buggy build and passes on the known-good one. Only then does ReproCam call the bug reproduced." |
| 1:16–1:24 | Live upload on the deployed site: bug1.mov dropped in, timeline running, verdict REPRODUCED · verified. Sped up, with jump cuts. | **live run · 4×** | "That was a replay. This one is live, on the deployed site." |
| 1:24–1:46 | bug1 replay, jump to the evidence step: the bug frame, SAM's 4 "price" boxes, then the single red box on the Total line (-$12.40). | **SAM proposes, Muse Spark Open decides.** SAM 3.1: "order total", 0 boxes · "price", 4 boxes. Muse Spark Open picks the Total line. | "For evidence, SAM 3.1 finds things, not meanings. Asked for 'order total', it finds nothing; asked for 'price', it finds four. Muse Spark Open picks the one the tester meant: the total, at minus twelve forty." |
| 1:46–2:00 | Back to bug2: the ticket (steps, failing line, known-good result, evidence image), then press "Run against fixed build": green toast. | Every bug report becomes a regression test | "The ticket comes with a test that fails now and passes once the bug is fixed. Every bug report becomes a regression test." |
| 2:00–2:17 | `docs/effort_sweep.png` full screen, then a one-line card about the sandbox. | On our 3 bugs no effort level was clearly better (7/9, 8/9, 7/9); we use low for speed and cost. · Generated tests run in a Modal Sandbox: no network, no secrets | "We measured it. On our three bugs, no effort level was clearly better, so we use low, for speed and cost. And generated tests never touch our keys: each one runs in a sandbox with no network." |
| 2:17–2:32 (OPTIONAL: Glimmer) | Eval table from the M9 report: base Glimmer, tuned Glimmer and the always-REPRODUCED baseline, balanced accuracy first. | Muse Glimmer 30B, LoRA-tuned as the judge · balanced accuracy on held-out tests: X% → Y% (baseline 50%) | "We also trained Muse Glimmer 30B into a judge, on labels from a buggy-versus-fixed oracle. On held-out tests its balanced accuracy went from X to Y." (Fill X and Y only from the eval report: the model judge's own accuracy, never the end-to-end number.) |
| 2:32–2:47 [2:17–2:47] | Architecture diagram: recording, then Voice Transcribe, Muse Spark, Playwright run with the known-good check, SAM 3.1, ticket. | Muse Voice Transcribe · Muse Spark · Muse Spark Open · SAM 3.1 (· Muse Glimmer) | "Every model in the product is a Meta model: Voice Transcribe for the narration, Muse Spark to understand the recording, Muse Spark Open to write and judge the test, and SAM 3.1 to find the evidence." |
| 2:47–3:00 | End card. | **For QA teams · support teams · crowd-testing companies** · https://admin-34790--reprocam-web.us-east.modal.run · https://github.com/nurnquant/reprocam | "For QA teams, support teams and crowd-testing companies: bug reports that prove themselves. Try it, and read the code." |

**Checks before the final cut**
- Every caption quoting a failure line matches `samples/bug2/events.jsonl` / `samples/bug1/segment.json` exactly.
- "6/9 on our bugs" is the deployed understanding (`docs/understand_stability.md`); results stay worded "on our
  3 bugs", no claim beyond what README states.
- The live segment's speed label matches the speed-up used.
- If the Glimmer slot stays, X and Y come from the eval report and are labelled as the model judge's accuracy on
  the held-out failed-assertion slice.
- 3:00 at most: read the narration aloud once with a timer. The attempt-2 shot (1:00–1:16) has the most slack.
