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
from backend.llm import chat, image_limit

PROMPTS = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT = "v1"  # v2 only becomes the default if it is at least as stable on all 3 bugs


def prompt_version() -> str:
    """prompts/understand_<version>.md, chosen by UNDERSTAND_PROMPT (default: DEFAULT_PROMPT)."""
    return os.getenv("UNDERSTAND_PROMPT") or DEFAULT_PROMPT
ACTIONS = ["goto", "click", "fill", "select", "press", "wait"]
# Frames differing from the last kept frame in fewer pixels than this (on a 320 px wide
# grayscale copy, per-pixel change > 24) are duplicates: a moving cursor changes ~10 px,
# a total or message updating changes 60+.
DUP_PIXELS = 30


def _small(path: Path) -> Image.Image:
    im = Image.open(path).convert("L")
    return im.resize((320, max(1, round(320 * im.height / im.width))))


def distinct_frames(run_dir: Path, frames: list[dict], limit: int | None = None) -> list[dict]:
    """Drop near-duplicate frames, always keeping the first and the last. With a limit (providers that cap
    images per request), keep the first, the last and the frames that changed most, in time order."""
    kept, changes, last = [], [], None
    for i, f in enumerate(frames):
        img = _small(run_dir / f["path"])
        changed = None
        if last is not None:
            changed = ImageChops.difference(last, img).point(lambda v: 255 if v > 24 else 0).histogram()[255]
            if i != len(frames) - 1 and changed < DUP_PIXELS:
                continue
        kept.append(f)
        changes.append(changed)
        last = img
    return limit_frames(kept, changes, limit)


def limit_frames(frames: list[dict], changes: list[int | None], limit: int | None) -> list[dict]:
    """At most `limit` frames: the first, the last, then the largest changes; time order is kept."""
    if not limit or len(frames) <= limit:
        return frames
    middle = sorted(range(1, len(frames) - 1), key=lambda i: (-(changes[i] or 0), i))[: max(0, limit - 2)]
    return [frames[i] for i in sorted({0, len(frames) - 1, *middle})]


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
        "properties": {
            "shows_app": {"type": "boolean", "description":
                          "true if the keyframes show the web app described by the element map (its pages, labels and "
                          "controls); false if the recording shows something else, e.g. another site or no app at all"},
            "steps": {"type": "array", "items": step}, "bug_claim": claim},
        "required": ["shows_app", "steps", "bug_claim"],
        "additionalProperties": False,
    }}}


def _image_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def understand(run_dir: str | Path, effort: str | None = None, provider: str | None = None,
               version: str | None = None) -> dict:
    run_dir = Path(run_dir)
    provider = provider or os.getenv("UNDERSTAND_PROVIDER") or None  # default: LLM_PROVIDER, like every stage
    manifest = json.loads((run_dir / "frames.json").read_text())
    transcript_file = run_dir / "transcript.json"
    transcript = json.loads(transcript_file.read_text())["transcript"].strip() if transcript_file.exists() else ""
    rows = dom_snapshot.load_or_build()
    frames = distinct_frames(run_dir, manifest["frames"], image_limit(provider))

    content = [{"type": "text", "text": f"Keyframes ({len(frames)} of {len(manifest['frames'])}, "
                                        f"duplicates removed{', most-changed kept' if len(frames) == image_limit(provider) else ''}), recording length {manifest['duration']:.1f}s:"}]
    for f in frames:
        content.append({"type": "text", "text": f"Frame {f['n']} at {f['t']:.1f}s"})
        content.append(_image_part(run_dir / f["path"]))
    content.append({"type": "text", "text": f"Narration transcript:\n{transcript or '(no narration)'}"})
    content.append({"type": "text", "text": f"Element map:\n{dom_snapshot.to_prompt(rows)}"})

    version = version or prompt_version()
    messages = [{"role": "system", "content": (PROMPTS / f"understand_{version}.md").read_text()},
                {"role": "user", "content": content}]
    text, meta = chat(messages, stage="understand", effort=effort, provider=provider,
                      response_format=schema(dom_snapshot.testids(rows), [f["n"] for f in frames]),
                      log_extra={"prompt_version": f"understand {version}"})
    meta["prompt_version"] = f"understand {version}"
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
