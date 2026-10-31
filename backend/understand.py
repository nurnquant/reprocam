"""Keyframes + transcript + element map -> steps.json (user steps and the bug claim).

    python -m backend.understand runs/bug1        # after: python -m backend.media samples/bug1.mov

Muse Spark Open (LLM_PROVIDER, EFFORT_UNDERSTAND) with structured output. The schema limits
selector_hint to testids in the element map and frame_ref to frames actually sent, so the
model cannot invent selectors.
"""
import base64
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops

from backend import dom_snapshot
from backend.llm import chat

PROMPT = Path(__file__).resolve().parent / "prompts" / "understand.md"
ACTIONS = ["goto", "click", "fill", "select", "press", "wait"]
# Frames differing from the last kept frame in fewer pixels than this (on a 320 px wide
# grayscale copy, per-pixel change > 24) are duplicates: a moving cursor changes ~10 px,
# a total or message updating changes 60+.
DUP_PIXELS = 30


def _small(path: Path) -> Image.Image:
    im = Image.open(path).convert("L")
    return im.resize((320, max(1, round(320 * im.height / im.width))))


def distinct_frames(run_dir: Path, frames: list[dict]) -> list[dict]:
    """Drop near-duplicate frames, always keeping the first and the last."""
    kept, last = [], None
    for i, f in enumerate(frames):
        img = _small(run_dir / f["path"])
        if last is not None and i != len(frames) - 1:
            diff = ImageChops.difference(last, img).point(lambda v: 255 if v > 24 else 0)
            if diff.histogram()[255] < DUP_PIXELS:
                continue
        kept.append(f)
        last = img
    return kept


def schema(testids: list[str], frame_ns: list[int]) -> dict:
    frame_ref = {"type": "integer", "enum": frame_ns}
    step = {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "action": {"type": "string", "enum": ACTIONS},
            "target": {"type": "string"},
            "selector_hint": {"type": ["string", "null"], "enum": testids + [None]},
            "value": {"type": ["string", "null"]},
            "frame_ref": frame_ref,
        },
        "required": ["n", "action", "target", "selector_hint", "value", "frame_ref"],
        "additionalProperties": False,
    }
    claim = {
        "type": "object",
        "properties": {k: {"type": "string"} for k in ("summary", "expected", "actual", "element")}
        | {"frame_ref": frame_ref},
        "required": ["summary", "expected", "actual", "element", "frame_ref"],
        "additionalProperties": False,
    }
    return {"type": "json_schema", "json_schema": {"name": "steps", "strict": True, "schema": {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": step}, "bug_claim": claim},
        "required": ["steps", "bug_claim"],
        "additionalProperties": False,
    }}}


def _image_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def understand(run_dir: str | Path, effort: str | None = None, provider: str | None = None) -> dict:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "frames.json").read_text())
    transcript_file = run_dir / "transcript.json"
    transcript = json.loads(transcript_file.read_text())["transcript"].strip() if transcript_file.exists() else ""
    rows = dom_snapshot.load_or_build()
    frames = distinct_frames(run_dir, manifest["frames"])

    content = [{"type": "text", "text": f"Keyframes ({len(frames)} of {len(manifest['frames'])}, "
                                        f"duplicates removed), recording length {manifest['duration']:.1f}s:"}]
    for f in frames:
        content.append({"type": "text", "text": f"Frame {f['n']} at {f['t']:.1f}s"})
        content.append(_image_part(run_dir / f["path"]))
    content.append({"type": "text", "text": f"Narration transcript:\n{transcript or '(no narration)'}"})
    content.append({"type": "text", "text": f"Element map:\n{dom_snapshot.to_prompt(rows)}"})

    messages = [{"role": "system", "content": PROMPT.read_text()}, {"role": "user", "content": content}]
    text, meta = chat(messages, stage="understand", effort=effort, provider=provider,
                      response_format=schema(dom_snapshot.testids(rows), [f["n"] for f in frames]))
    result = json.loads(text)
    for i, step in enumerate(result["steps"], 1):  # contract numbers steps from 1
        step["n"] = i

    steps = {"app_url": os.getenv("APP_URL", "http://localhost:5173"), **result}
    (run_dir / "steps.json").write_text(json.dumps(steps, indent=2))
    meta["frames_sent"] = [f["n"] for f in frames]
    (run_dir / "understand_meta.json").write_text(json.dumps(meta, indent=2))
    return {"steps": steps, "meta": meta}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.understand runs/<name>")
    out = understand(sys.argv[1])
    m = out["meta"]
    print(f"{m['model']} · {m['provider']} · effort {m['effort']} · frames {m['frames_sent']}")
    print(f"tokens in {m['prompt_tokens']} out {m['completion_tokens']} "
          f"(reasoning {m['reasoning_tokens']}) · {m['latency_s']}s · cost {m['cost_usd']}\n")
    for s in out["steps"]["steps"]:
        print(f"  {s['n']:>2}. {s['action']:<6} {s['selector_hint'] or '-':<28} "
              f"{repr(s['value']) if s['value'] else '':<14} {s['target']}  [f{s['frame_ref']}]")
    print("\nbug_claim:", json.dumps(out["steps"]["bug_claim"], indent=2))
