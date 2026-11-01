# ReproCam demo video: 3:00 script (draft)

For: the hackathon judges. Screen recording of the live site plus a short phone clip; voice-over recorded
separately. Every failure line, verdict and number below is copied from a real run (`samples/bug2/`,
`samples/bug1/`, `data/effort_sweep.jsonl`); none is staged or edited.

**Before recording**
- Use the cached replays (`/?sample=bug2`, `/?sample=bug1`) at 2× speed. They cost $0 and always look the same.
  They were recorded with Muse Spark Open on Fireworks, so their badges say Fireworks; the live app now runs on
  Baseten. Don't say "Baseten" over a replay.
- The phone clip is the bug2 recording itself (`samples/bug2.mov`), or a re-film of the same steps.
- Glimmer segment (2:25–2:40) only if M9 has an eval result. Without one, cut it and give the 15 s to the
  architecture shot (alternate timings in brackets).

| Time | Shot | On-screen caption | Narration |
|---|---|---|---|
| 0:00–0:06 | Title card: ReproCam logo on a plain background. | **Everything shown was built during this hackathon.** | "Everything shown was built during this hackathon." |
| 0:06–0:20 | Phone clip of the bug2 recording: Pebble Night Light in the basket, tester taps "−" at quantity 1, the badge reads 0, the checkout still says $18.50. | A tester's bug recording, with narration | "A tester finds a bug and records it: the basket says zero items, but checkout still charges eighteen fifty. Normally that becomes a ticket someone has to reproduce by hand." |
| 0:20–0:35 | Site home, then the bug2 sample replay at 2×. The timeline lights up: frames, then Muse Voice Transcribe, then understanding, each with its model · provider · effort badge. | Cached replay of a real run · $0 | "ReproCam takes the recording. Muse Voice Transcribe turns the narration into text, and Muse Spark Open reads the keyframes and the transcript." |
| 0:35–0:50 | Zoom in on the card "What the agent understood": 4 steps (product page, View basket, "−", Checkout) and the claim. | Steps use only element ids from the store's map | "It writes down the steps and what the tester claims is wrong. It may only use element ids that exist in the app, so it can't invent selectors." |
| 0:50–1:12 | Attempt 1: the generated test, then the red run line, then the known-good check failing. Hold on the two real failure lines. | Buggy build: `Expected value: '$0.00' · Actual value: $18.50`, then on the known-good build: `basket badge should show 0 after removing only item · Expected value: '0' · Actual value: 1` | "It writes a Playwright test and runs it. The test fails on the buggy build, which looks like success. But ReproCam runs the same test on a known-good build too, and it fails there as well. So the test's idea of correct behaviour was wrong, and the agent tries again." |
| 1:12–1:30 | Attempt 2: the new test (badge and total must agree), red on buggy, then the "passes on fixed build" line turns green. Status pill: REPRODUCED · verified. | Attempt 2: `checkout total should be $0.00 when basket is empty · Actual value: $18.50` · passes on the known-good build | "The second test checks that the total agrees with the basket. It fails on the buggy build and passes on the known-good one. Only now does ReproCam call the bug reproduced." |
| 1:30–1:55 | Switch to the bug1 replay, jump to the evidence step. Show the bug frame, SAM's 4 "price" boxes, then the single red box on the Total line (-$12.40). | **SAM proposes, Muse Spark decides.** SAM 3.1: "order total", 0 boxes · "price", 4 boxes. Muse Spark picks the Total line. | "For evidence, SAM 3.1 finds things, not meanings. Asked for 'order total', it finds nothing; asked for 'price', it finds four. Muse Spark looks at the four and picks the one the tester meant: the total, at minus twelve forty." |
| 1:55–2:10 | Back to bug2: the ticket (steps, failing line, known-good result, evidence image), then press "Run against fixed build": green toast. | Every bug report becomes a regression test | "The ticket comes with a test that fails now and passes once the bug is fixed. Every bug report becomes a regression test." |
| 2:10–2:25 [2:10–2:30] | `docs/effort_sweep.png` full screen, then a one-line card about the sandbox. | On our 3 bugs no effort level was clearly better (7/9, 8/9, 7/9); we use low for speed and cost. · Generated tests run in a Modal Sandbox: no network, no secrets | "We measured it. On our three bugs, no effort level was clearly better, so we use low, for speed and cost. And generated tests never touch our keys: each runs in a sandbox with no network." |
| 2:25–2:40 (OPTIONAL: Glimmer) | Eval table from the M9 report: base Glimmer, tuned Glimmer and the always-REPRODUCED baseline, balanced accuracy first. | Muse Glimmer 30B, LoRA-tuned as the judge · balanced accuracy on held-out tests: X% → Y% (baseline 50%) | "We also trained Muse Glimmer 30B into a judge, on labels from a buggy-versus-fixed oracle. On held-out tests its balanced accuracy went from X to Y." (Fill X and Y only from the eval report; this is the model judge's own accuracy, never the end-to-end number.) |
| 2:40–2:52 [2:30–2:52] | Architecture diagram: recording, then Voice Transcribe, Muse Spark, Playwright run with the known-good check, SAM 3.1, ticket. | Muse Voice Transcribe · Muse Spark · Muse Spark Open · SAM 3.1 (· Muse Glimmer) | "Every model in the product is a Meta model: Voice Transcribe for the narration, Muse Spark to understand and write tests, SAM 3.1 to find the evidence." |
| 2:52–3:00 | Site URL on screen over the home page. | For QA teams and solo developers · next: CI integration, native mobile · the site URL | "ReproCam is for anyone who files bug reports. Next: run it in CI, and on native mobile apps. Try it at the link." |

**Checks before the final cut**
- Every caption quoting a failure line matches `samples/bug2/events.jsonl` / `samples/bug1/segment.json` exactly.
- Results are worded "on our 3 bugs"; no claim beyond what README states.
- If the Glimmer slot stays, X and Y come from the eval report and are labelled as the model judge's accuracy
  on the held-out failed-assertion slice.
- 3:00 at most: read the narration aloud once with a timer; the attempt-1 shot (0:50–1:12) is the one to trim.
