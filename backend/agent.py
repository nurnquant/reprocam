"""The verify loop: video -> steps -> test -> run -> judge -> retry (<= 3) -> fix check.

    python -m backend.agent samples/bug1.mov              # full pipeline
    python -m backend.agent samples/bug1.mov --from-steps # reuse runs/bug1/steps.json

Events go to runs/<name>/events.jsonl (contract in BUILD_PLAN). Every verdict is logged to
data/judge_log.jsonl together with the oracle: the same test re-run on the fixed build.
The oracle never steers the loop; only the judge does (in real use there is no fixed build).
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from backend import media, testgen
from backend.judge import judge
from backend.llm import TruncatedAnswer, effort_for
from backend.runner import failure_summary, run_test
from backend.segment import evidence
from backend.ticket import write_ticket
from backend.transcribe import MODEL as TRANSCRIBE_MODEL
from backend.transcribe import transcribe
from backend.understand import prompt_version as understand_prompt_version
from backend.understand import understand

ROOT = Path(__file__).resolve().parent.parent
JUDGE_LOG = ROOT / "data" / "judge_log.jsonl"
MAX_ATTEMPTS = 3
NOT_APP = "Not a recording of the app under test"
KNOWN_GOOD_FEEDBACK = ("Your expected behavior is wrong: it also fails on a build where the bug is fixed; re-read "
                       "the claim. On that build the test saw: {seen}. What the known-good build shows is correct "
                       "behaviour, so assert something that holds there and still fails on the buggy build (the "
                       "tester's symptom). The claim's 'expected' is the tester's guess at the fix and may be wrong.")
# Sample videos whose bug is known, so judge log rows carry a bug id (None for real uploads).
SAMPLE_BUGS = {"bug1": "neg_total", "bug2": "qty_stepper", "bug3": "zip_hang"}

sys.path.insert(0, str(ROOT / "scripts"))
from serve_store import store_running  # noqa: E402


class Run:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.started = time.time()
        self.events = run_dir / "events.jsonl"
        self.events.write_text("")
        self.calls: list[dict] = []

    def emit(self, stage, status, detail, meta=None, attempt=None, artifact=None, record=True):
        if meta and record and status != "start":
            self.calls.append(meta)
        event = {"t": round(time.time() - self.started, 2), "stage": stage, "status": status,
                 "model": meta and meta.get("model"), "provider": meta and meta.get("provider"),
                 "effort": meta and meta.get("effort"), "attempt": attempt, "detail": detail,
                 "artifact": artifact and os.path.relpath(artifact, self.dir)}
        if meta and meta.get("pick_provider"):
            event["pick_provider"] = meta["pick_provider"]
        with self.events.open("a") as f:
            f.write(json.dumps(event) + "\n")
        tag = f"[{event['t']:6.1f}s] {stage:<10} {status:<5}"
        badge = f" ({meta['provider']} · effort {meta['effort']})" if meta and meta.get("effort") else ""
        print(f"{tag} {detail}{badge}")

    def cost(self) -> float | None:
        known = [c["cost_usd"] for c in self.calls if c.get("cost_usd") is not None]
        return round(sum(known), 4) if known else None


def known_good_target(spec: str | None, app_url: str) -> tuple[str, str] | None:
    """Optional known-good build: 'fixed' = the practice store's ?fixed=1, or a URL of a build that
    works (e.g. the last release). None = off. Returns (app url, label)."""
    if not spec:
        return None
    if spec == "fixed":
        return app_url, "fixed build (?fixed=1)"
    return spec.rstrip("/"), f"known-good build ({spec})"


def outcome_label(final: dict) -> tuple[str, str]:
    """(label, tone) shown in the CLI, the UI and the ticket. tone: good | warn | bad."""
    if final["verdict"] != "REPRODUCED":
        return final["verdict"].replace("_", " "), "bad"
    build = "fixed build" if (final.get("known_good") or "").startswith("fixed") else "known-good build"
    if final.get("confirmed") is True:
        return "REPRODUCED · verified against known-good build", "good"
    if final.get("confirmed") is False:
        return f"REPRODUCED · NOT CONFIRMED (also fails on {build})", "warn"
    return "REPRODUCED · not verified (no known-good build given)", "good"


def failure_text(result: dict) -> str:
    return f"{result['outcome']} ({result.get('exc_type')}): {result.get('message', '')}"


def log_verdict(run_id, bug_id, attempt, claim, code, result, verdict, oracle, meta, prompt_version=None):
    JUDGE_LOG.parent.mkdir(exist_ok=True)
    row = {"ts": round(time.time(), 1), "run_id": run_id, "bug_id": bug_id, "attempt": attempt,
           "bug_claim": claim, "test_code": code,
           "test_hash": hashlib.sha256(code.encode()).hexdigest()[:12],
           "pytest_output": (failure_text(result) + "\n" + result.get("output", ""))[:3000],
           "verdict": verdict["verdict"], "decided_by": verdict["decided_by"], "reason": verdict["reason"],
           "oracle": oracle, "judge_provider": meta and meta["provider"], "judge_effort": meta and meta["effort"],
           "testgen_prompt": prompt_version}
    with JUDGE_LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")


def make_evidence(run: Run, run_dir: Path, from_steps: bool):
    """SAM 3.1 (+ Muse Spark pick, or Muse Spark fallback) -> evidence.png. Never blocks the run."""
    if not (run_dir / "frames.json").exists():
        return
    run.emit("segment", "start", "locating the broken element (SAM 3.1)")
    try:
        r = asyncio.run(evidence(run_dir))
    except Exception as e:  # noqa: BLE001
        run.emit("segment", "fail", f"no evidence image: {e.__class__.__name__}: {str(e)[:120]}")
        return
    run.calls.extend(r["tried"] + r["calls"])  # SAM requests (frames processed) + Muse Spark pick/locate
    tried = ", ".join(f"'{t['concept']}' {t['on_bug_frame']}" for t in r["tried"])
    frames = sum(t["frames_processed"] or 0 for t in r["tried"])
    run.emit("segment", "ok", f"{r['method']} · SAM {r['sam_mode']} mode, boxes on bug frame: {tried}; "
             f"{frames} frame(s) processed",
             {"model": "sam-3.1", "provider": "meta", "effort": None,
              "pick_provider": next((c.get("provider") for c in r["calls"]), None)},
             artifact=run_dir / "evidence.png", record=False)  # calls already recorded above


def run_pipeline(video: str, bug_id: str | None = None, from_steps: bool = False,
                 run_dir: Path | None = None, known_good: str | None = None, evidence: bool = True) -> dict:
    """Run the whole loop for one video into run_dir (default runs/<video stem>). Always ends by
    writing result.json, also when a stage crashes, so live event streams know the run is over."""
    video = Path(video)
    run_dir = Path(run_dir) if run_dir else ROOT / "runs" / video.stem
    run_dir.mkdir(parents=True, exist_ok=True)
    for old in run_dir.glob("attempt_*"):
        shutil.rmtree(old)
    for old in ("result.json", "ticket.md", "evidence.png", "segment.json"):
        (run_dir / old).unlink(missing_ok=True)
    run = Run(run_dir)
    run_id = f"{run_dir.name}-{int(run.started)}"
    bug_id = bug_id or SAMPLE_BUGS.get(video.stem)
    app_url = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    try:
        kg = known_good_target(known_good if known_good is not None else os.getenv("KNOWN_GOOD_URL"), app_url)
        return _pipeline(run, run_dir, video, run_id, bug_id, app_url, from_steps, kg, evidence)
    except Exception as e:
        run.emit("error", "fail", f"{e.__class__.__name__}: {str(e)[:200]}")
        result = {"verdict": "ERROR", "error": f"{e.__class__.__name__}: {e}", "run_id": run_id, "bug_id": bug_id,
                  "seconds": round(time.time() - run.started, 1), "cost_usd": run.cost()}
        (run_dir / "result.json").write_text(json.dumps(result, indent=2))
        raise


def _pipeline(run: Run, run_dir: Path, video: Path, run_id: str, bug_id: str | None, app_url: str,
              from_steps: bool, kg: tuple[str, str] | None, evidence: bool = True) -> dict:
    if from_steps:
        run.emit("understand", "ok", "reusing cached steps.json", artifact=run_dir / "steps.json")
    else:
        run.emit("frames", "start", f"extracting audio and keyframes from {video.name}")
        prepared = media.prepare(video, run_dir)
        run.emit("frames", "ok", f"{len(prepared['frames'])} keyframes", artifact=run_dir / "frames.json")
        if prepared["audio"]:
            run.emit("transcribe", "start", "transcribing narration")
            t = transcribe(run_dir / "audio.wav")
            (run_dir / "transcript.json").write_text(json.dumps(t, indent=2))
            asr_price = os.getenv("PRICE_META_ASR")  # USD per minute of audio
            asr_cost = round(t.get("audioDurationMs", 0) / 60000 * float(asr_price), 6) if asr_price else None
            run.emit("transcribe", "ok", f'"{t["transcript"].strip()[:80]}"',
                     {"stage": "transcribe", "model": TRANSCRIBE_MODEL, "provider": "meta", "effort": None,
                      "cost_usd": asr_cost},
                     artifact=run_dir / "transcript.json")
        run.emit("understand", "start", "reading keyframes + narration")
        u = understand(run_dir)
        run.emit("understand", "ok", f"[{u['meta']['prompt_version']}] {len(u['steps']['steps'])} steps; "
                 f"claim: {u['steps']['bug_claim']['summary']}",
                 u["meta"], artifact=run_dir / "steps.json")
    steps = json.loads((run_dir / "steps.json").read_text())
    claim = steps["bug_claim"]
    grounded = sum(1 for st in steps.get("steps", []) if st.get("selector_hint"))
    # Stop only when the model says "not the app" AND its own steps agree (fewer than 2 element-map
    # ids). Measured: the flag alone was wrongly false on 2 of 18 real recordings, each time with
    # 7-9 grounded steps; real non-app videos give ~1 step with none.
    if steps.get("shows_app") is False and grounded < 2:
        run.emit("understand", "fail", NOT_APP)
        final = {"verdict": "NOT_APP", "attempt": 0, "confirmed": None, "known_good": kg and kg[1], "fixcheck": None,
                 "label": NOT_APP, "tone": "bad"}
        return _save(run, run_dir, run_id, bug_id, final)

    previous, final, verdict = [], None, None
    unconfirmed = None  # best fallback: judge said REPRODUCED but the known-good build failed too
    with store_running(app_url):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            adir = run_dir / f"attempt_{attempt}"
            run.emit("testgen", "start", f"writing test (effort {effort_for('testgen')})", attempt=attempt)
            try:
                code, notes, gen_meta = testgen.generate(steps, previous)
            except TruncatedAnswer as e:  # counts as a failed attempt, not a crashed run
                run.emit("testgen", "fail", str(e), e.meta, attempt)
                previous.append({"test_code": "(none)", "outcome": "no test", "failure": str(e),
                                 "feedback": "Your previous answer ran out of output tokens before the test. "
                                 "Think less and write the test directly."})
                verdict = {"verdict": "TEST_ERROR", "decided_by": "rule", "reason": str(e)}
                if attempt < MAX_ATTEMPTS:
                    run.emit("judge", "retry", "no test came back; writing it again", attempt=attempt)
                continue
            adir.mkdir()
            (adir / "test_repro.py").write_text(code)
            run.emit("testgen", "ok", f"[{gen_meta['prompt_version']}] {notes}", gen_meta, attempt,
                     adir / "test_repro.py")

            problem = testgen.lint(code)
            if problem:
                result = {"outcome": "error", "phase": "lint", "exc_type": "Lint", "message": problem, "output": ""}
                run.emit("run", "fail", f"not run: {problem}", attempt=attempt)
            else:
                run.emit("run", "start", "running on buggy build (?fixed=0)", attempt=attempt)
                result = run_test(code, adir / "buggy", app_url, fixed=False)
                run.emit("run", "ok" if result["outcome"] == "pass" else "fail",
                         f"{result['outcome']}: {failure_summary(result.get('message'))[:160] or 'passed'}",
                         attempt=attempt, artifact=result.get("screenshot"))

            try:
                verdict, judge_meta = judge(claim, code, result)
            except TruncatedAnswer as e:  # no verdict came back: not reproduced, try again
                verdict, judge_meta = {"verdict": "NOT_REPRODUCED", "decided_by": "rule", "reason": str(e),
                                       "feedback_for_generator": ""}, e.meta
            (adir / "verdict.json").write_text(json.dumps(verdict, indent=2))
            run.emit("judge", "ok" if verdict["verdict"] == "REPRODUCED" else "fail",
                     f"{verdict['verdict']} ({verdict['decided_by']}): {verdict['reason']}",
                     judge_meta, attempt, adir / "verdict.json")

            # Known-good build (optional): the same test must pass where the bug is fixed. It is the
            # oracle in the judge log, and if the judge said REPRODUCED but the test fails there too,
            # the test's expected behaviour is wrong: a legitimate retry trigger.
            good = run_test(code, adir / "known_good", kg[0], fixed=True) if kg and not problem else None
            oracle = {"buggy": result["outcome"], "fixed": (good or result)["outcome"]} if kg else None
            log_verdict(run_id, bug_id, attempt, claim, code, result, verdict, oracle, judge_meta,
                        gen_meta["prompt_version"])

            if verdict["verdict"] == "REPRODUCED":
                confirmed = None if good is None else good["outcome"] == "pass"
                if good is not None:
                    run.emit("fixcheck", "ok" if confirmed else "fail",
                             f"passes on {kg[1]}" if confirmed
                             else f"also fails on {kg[1]}: {failure_summary(good.get('message'))[:150]}",
                             attempt=attempt, artifact=good.get("screenshot"))
                if confirmed is False and attempt < MAX_ATTEMPTS:
                    unconfirmed = unconfirmed or {"attempt": attempt, "adir": adir, "result": result, "good": good,
                                                  "verdict": verdict}
                    previous.append({"test_code": code, "outcome": "assert_fail on the buggy build AND on the "
                                     "known-good build", "failure": failure_text(good),
                                     "feedback": KNOWN_GOOD_FEEDBACK.format(
                                         seen=failure_summary(good.get("message")) or good["outcome"])})
                    run.emit("judge", "retry", "expected behaviour is wrong: the test also fails on the known-good "
                             "build", attempt=attempt)
                    continue
                final = finish(run, run_dir, run_id, from_steps, kg, attempt, adir, result, good, verdict, confirmed,
                               evidence)
                break
            previous.append({"test_code": code, "outcome": result["outcome"],
                             "failure": failure_text(result), "feedback": verdict["feedback_for_generator"]})
            if attempt < MAX_ATTEMPTS:
                run.emit("judge", "retry", "feeding judge feedback back to the test writer", attempt=attempt)

    if final is None and unconfirmed:  # no later attempt did better: report the unconfirmed reproduction
        u = unconfirmed
        run.emit("judge", "fail", f"no attempt passed on the known-good build; reporting attempt {u['attempt']}, "
                 "which reproduced the symptom but is not confirmed", attempt=u["attempt"])
        final = finish(run, run_dir, run_id, from_steps, kg, u["attempt"], u["adir"], u["result"], u["good"],
                       u["verdict"], False, evidence)
    if final is None:
        final = {"verdict": verdict["verdict"], "attempt": MAX_ATTEMPTS, "confirmed": None,
                 "known_good": kg and kg[1], "fixcheck": None}
        final["label"], final["tone"] = outcome_label(final)
    return _save(run, run_dir, run_id, bug_id, final)


def _save(run: Run, run_dir: Path, run_id: str, bug_id: str | None, final: dict) -> dict:
    final.update(run_id=run_id, bug_id=bug_id, testgen_prompt=f"testgen {testgen.prompt_version()}",
                 understand_prompt=f"understand {understand_prompt_version()}",
                 seconds=round(time.time() - run.started, 1), cost_usd=run.cost(),
                 model_calls=[{k: c.get(k) for k in ("stage", "model", "provider", "effort", "prompt_tokens",
                                                     "completion_tokens", "reasoning_tokens", "finish_reason",
                                                     "max_tokens", "frames_processed", "cost_usd")
                              if c.get(k) is not None} for c in run.calls])
    (run_dir / "result.json").write_text(json.dumps(final, indent=2))
    return final


def finish(run: Run, run_dir: Path, run_id: str, from_steps: bool, kg, attempt: int, adir: Path, result: dict,
           good: dict | None, verdict: dict, confirmed: bool | None, evidence: bool = True) -> dict:
    """Result for a reproduced attempt, plus evidence and ticket."""
    final = {"verdict": "REPRODUCED", "attempt": attempt, "confirmed": confirmed,
             "known_good": kg and kg[1], "fixcheck": good and good["outcome"],
             "test": f"{adir.name}/test_repro.py", "failure": failure_text(result)}
    final["label"], final["tone"] = outcome_label(final)
    if evidence:
        make_evidence(run, run_dir, from_steps)
    models = sorted({c["model"] for c in run.calls if c.get("model")})
    ticket = write_ticket(run_dir, adir, result, good, verdict,
                          {"run_id": run_id, "attempt": attempt, "models": models,
                           "label": final["label"], "known_good": final["known_good"]})
    run.emit("ticket", "ok", "bug report written", attempt=attempt, artifact=ticket)
    return final


TONE = {"good": "\033[32m", "warn": "\033[33m", "bad": "\033[31m"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--bug-id")
    ap.add_argument("--from-steps", action="store_true", help="reuse runs/<name>/steps.json")
    ap.add_argument("--known-good", help="'fixed' (the store's ?fixed=1) or the URL of a build without the bug; "
                    "default: KNOWN_GOOD_URL from .env, else off")
    args = ap.parse_args()
    out = run_pipeline(args.video, args.bug_id, args.from_steps, known_good=args.known_good)
    color = TONE.get(out.get("tone"), "") if sys.stdout.isatty() else ""
    print(f"\n{color}{out['label']}\033[0m" if color else f"\n{out['label']}", end="")
    print(f" · attempt {out['attempt']} · {out['seconds']}s · model cost ${out['cost_usd']}")
