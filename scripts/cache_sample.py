"""Freeze a finished run as a replayable sample (zero API cost on the public demo).

Run from the reprocam folder:  python scripts/cache_sample.py bug1 [--title "..."]
Copies runs/<id>/ -> samples/<id>/ (events with their original timing, steps, keyframes sent to
the model, test + verdict + results per attempt, evidence, ticket) and adds video.mp4, a
browser-playable copy of samples/<id>.mov with the narration.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = ["events.jsonl", "result.json", "steps.json", "frames.json", "transcript.json", "understand_meta.json",
        "segment.json", "evidence.png", "ticket.md"]
KEEP_ATTEMPT = ["test_repro.py", "verdict.json", "buggy/result.json", "fixed/result.json"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--title", help="one line for the sample picker")
    args = ap.parse_args()
    src, dst = ROOT / "runs" / args.id, ROOT / "samples" / args.id
    if not (src / "result.json").exists():
        sys.exit(f"{src} has no result.json; run the agent first")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for name in KEEP:
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    frames = json.loads((src / "frames.json").read_text())
    sent = set(json.loads((src / "understand_meta.json").read_text()).get("frames_sent", []))
    (dst / "keyframes").mkdir()
    for f in frames["frames"]:
        if f["n"] in sent:
            shutil.copy2(src / f["path"], dst / f["path"])
    for attempt in sorted(src.glob("attempt_*")):
        for name in KEEP_ATTEMPT:
            if (attempt / name).exists():
                (dst / attempt.name / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(attempt / name, dst / attempt.name / name)
        for build in ("buggy", "fixed"):  # final screenshot of each run
            shots = sorted((attempt / build / "artifacts").rglob("*.png"))
            if shots:
                shutil.copy2(shots[-1], dst / attempt.name / build / "screenshot.png")

    video = Path(frames["video"])
    video = video if video.is_absolute() else ROOT / video
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", "scale=1280:-2", "-c:v", "libx264",
                    "-crf", "28", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", str(dst / "video.mp4")], check=True)

    result = json.loads((src / "result.json").read_text())
    claim = json.loads((src / "steps.json").read_text())["bug_claim"]
    (dst / "sample.json").write_text(json.dumps({
        "id": args.id, "bug_id": result.get("bug_id"), "title": args.title or claim["summary"],
        "verdict": result["verdict"], "attempts": result.get("attempt"), "seconds": result.get("seconds"),
        "cost_usd": result.get("cost_usd")}, indent=2))
    size = sum(p.stat().st_size for p in dst.rglob("*") if p.is_file())
    print(f"samples/{args.id}: {sum(1 for p in dst.rglob('*') if p.is_file())} files, {size / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
