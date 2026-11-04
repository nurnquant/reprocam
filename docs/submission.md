# Submission kit (paste-ready)

Submit at https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit before **Wed Nov 4, 9:00 PM ET**
(target: 5:00 PM).

## Fields
- **Project name:** ReproCam
- **Tagline:** Film a bug, get a failing test that proves it.
- **Track:** Indie Developer
- **Problem statement:** Build for Your World
- **Team:** Nur (solo)
- **Repository (public):** https://github.com/nurnquant/reprocam
- **Live demo:** https://admin-34790--reprocam-web.us-east.modal.run
- **Demo video (3 min):** <YouTube unlisted link>
- **X post (Most Viral):** <link to the post>
- **Bonus prizes to flag:** Best Agentic Use-Case; Best Build on Meta Open Weight Models (Muse Spark Open on Baseten)

## Description
ReproCam turns a narrated bug recording into a failing Playwright test, and proves it before filing.

A tester records a bug and says what went wrong. ReproCam transcribes the narration (Muse Voice Transcribe),
reads the video frames (Muse Spark on the Meta Model API), and writes a Playwright test (Muse Spark Open, open
weights, on Baseten's hackathon endpoint). The test runs in an isolated Modal Sandbox with no network and no
secrets. ReproCam only reports a bug as reproduced when the test fails on the buggy build for the claimed reason
*and* passes on a known-good build; if its expectation is wrong, it retries. For evidence, SAM 3.1 proposes
candidate elements and Muse Spark Open picks the broken one. Every confirmed bug becomes a regression test.

**Why:** I'm a senior SDET. "Can't reproduce" is where bug reports die. This is the tool I wanted.

**Built during the hackathon:** everything: the practice store with planted bugs, the agent pipeline, the
verify loop with known-good checking, the UI, the sandboxed deployment, and the measurements.

**Measured on our 3 bugs:** the demo run of each reproduces and verifies; over repeated runs, effort levels verified
7/9, 8/9, 7/9 (we use low: ~55 s, ~$0.02 per run on Fireworks; bug2 is the weak one); understanding is right 6 of 9
times, which is why ReproCam proves every bug before filing.

**Next:** distil the judge into Muse Glimmer 30B (training data and settings ready), CI integration, mobile apps.

## X post
(Attach the video to the post. Under X's 280-character limit with the video attached.)

I'm a senior SDET. The worst words in my job: "can't reproduce."

So for the @AIatMeta hackathon I built ReproCam: film a bug, narrate it, and Muse models write a failing Playwright test, then prove it on a fixed build.

https://admin-34790--reprocam-web.us-east.modal.run
https://github.com/nurnquant/reprocam

## Final checks before pressing Submit
- [ ] Repo opens in a private/incognito window (public)
- [ ] Video link plays in a private window (Unlisted is fine; Private is NOT)
- [ ] Live site loads and "Try a sample bug" works on a phone
- [ ] README video link filled in and pushed
