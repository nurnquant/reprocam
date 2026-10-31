"""ffmpeg helpers: narration audio for Voice Transcribe, keyframes for Muse Spark.

    python -m backend.media samples/bug1.mov

writes runs/<video stem>/audio.wav + keyframes/ + frames.json and prints the transcript
(skipped with a note when MODEL_API_KEY is not set).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Muse Voice Transcribe is native at 24 kHz (16 kHz is resampled server-side).
SAMPLE_RATE = 24000
MAX_FRAMES = 24
MAX_WIDTH = 1280
# Scene score is computed on a 320 px copy. In a screen recording a page change scores
# ~0.03-0.15, a text change (promo applied, total updated) only ~0.0025-0.004, and an idle
# screen (cursor blink, hover) stays under ~0.001. So the threshold is very low on purpose.
SCENE_THRESHOLD = 0.002
# Gaps longer than this get filled with evenly spaced frames, so a static stretch
# (e.g. a spinner that never stops) is still represented.
MAX_GAP_S = 1.0

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


class MediaError(RuntimeError):
    pass


def _run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"{args[0]} failed: {proc.stderr.strip()[-400:]}")
    return proc


def probe(video: str | Path) -> dict:
    """Duration in seconds, frame size, and whether there is an audio track."""
    out = _run(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(video)]).stdout
    info = json.loads(out)
    streams = info.get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    if v is None:
        raise MediaError(f"{video}: no video stream")
    return {
        "duration": float(info["format"]["duration"]),
        "width": int(v["width"]),
        "height": int(v["height"]),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
    }


def extract_audio(video: str | Path, out_wav: str | Path) -> Path:
    """Mono 16-bit PCM WAV at 24 kHz, the format Voice Transcribe expects."""
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn",
          "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(out_wav)])
    return Path(out_wav)


def scene_changes(video: str | Path, threshold: float = SCENE_THRESHOLD) -> list[tuple[float, float]]:
    """[(time_s, scene_score)] for frames that differ visibly from the one before."""
    proc = _run(["ffmpeg", "-v", "info", "-i", str(video), "-an",
                 "-vf", f"scale=320:-2,select='gt(scene,{threshold})',metadata=print",
                 "-f", "null", "-"])
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    scores = [float(s) for s in re.findall(r"lavfi\.scene_score=([\d.]+)", proc.stderr)]
    return list(zip(times, scores))


def pick_timestamps(duration: float, changes: list[tuple[float, float]],
                    max_frames: int = MAX_FRAMES, max_gap: float = MAX_GAP_S) -> list[float]:
    """Strongest scene changes first, plus the first and last moment, then fill big gaps."""
    last = max(duration - 0.1, 0.0)
    picked = {0.0, last}
    for t, _ in sorted(changes, key=lambda c: -c[1]):
        if len(picked) >= max_frames:
            break
        if all(abs(t - p) >= 0.25 for p in picked):
            picked.add(round(t, 3))
    while len(picked) < max_frames:
        ts = sorted(picked)
        gap, start = max((b - a, a) for a, b in zip(ts, ts[1:])) if len(ts) > 1 else (0, 0)
        if gap <= max_gap:
            break
        picked.add(round(start + gap / 2, 3))
    return sorted(picked)


def extract_keyframes(video: str | Path, out_dir: str | Path, max_frames: int = MAX_FRAMES) -> list[dict]:
    """JPEG keyframes (≤ max_frames, ≤ 1280 px wide). Returns [{n, t, path}] in time order."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()
    duration = probe(video)["duration"]
    frames = []
    for n, t in enumerate(pick_timestamps(duration, scene_changes(video), max_frames)):
        path = out_dir / f"frame_{n:02d}.jpg"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
              "-frames:v", "1", "-vf", f"scale='min({MAX_WIDTH},iw)':-2", "-q:v", "3", str(path)])
        frames.append({"n": n, "t": t, "path": str(path)})
    return frames


def prepare(video: str | Path, run_dir: str | Path | None = None) -> dict:
    """Audio + keyframes for one video into run_dir (default runs/<stem>/)."""
    video = Path(video)
    run_dir = Path(run_dir) if run_dir else RUNS_DIR / video.stem
    run_dir.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    audio = extract_audio(video, run_dir / "audio.wav") if info["has_audio"] else None
    frames = extract_keyframes(video, run_dir / "keyframes")
    for f in frames:
        f["path"] = os.path.relpath(f["path"], run_dir)
    manifest = {"video": str(video), **info, "audio": audio and audio.name, "frames": frames}
    (run_dir / "frames.json").write_text(json.dumps(manifest, indent=2))
    return {**manifest, "run_dir": str(run_dir)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.media <video>")
    result = prepare(sys.argv[1])
    print(f"video     {result['video']}  {result['duration']:.1f}s  {result['width']}x{result['height']}")
    print(f"frames    {len(result['frames'])} -> {result['run_dir']}/keyframes/")
    print("          at " + ", ".join(f"{f['t']:.1f}s" for f in result["frames"]))
    if not result["audio"]:
        print("audio     none (video has no audio track)")
        sys.exit(0)

    from backend.transcribe import transcribe  # noqa: E402

    if not os.getenv("MODEL_API_KEY"):
        print("transcript skipped: MODEL_API_KEY is not set in .env")
        sys.exit(0)
    out = transcribe(Path(result["run_dir"]) / "audio.wav")
    (Path(result["run_dir"]) / "transcript.json").write_text(json.dumps(out, indent=2))
    print(f"transcript ({out.get('audioDurationMs', 0) / 1000:.1f}s audio, {out['latency_s']:.1f}s):")
    print(f"  {out.get('transcript', '').strip()}")
