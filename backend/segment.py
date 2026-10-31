"""SAM 3.1: find the broken element in the video and draw it on the bug frame -> evidence.png.

    python -m backend.segment runs/bug1 [--concept "order total" --concept discount ...]

Request and stream handling are ported from the Meta cookbook (07_sam/01_api_basics/python/
sam_api.py): upload an MP4 with purpose=user_data, stream a Responses call to sam-3.1 with one
noun phrase, parse ONLY with meta_sam_parser. The video is re-encoded at a fixed 5 fps and
1280 px wide, so SAM's frame_index maps to time as t = frame_index / 5 and boxes share the
keyframes' pixel scale.

SAM finds UI objects (buttons, prices) well but not meanings ("order total" returns nothing,
"price" returns every price). So:
  1. try the claim's element, then generic concepts, until SAM has boxes on the bug frame;
  2. one box -> done; several -> Muse Spark picks one from a numbered overlay;
  3. no boxes at all -> fallback: Muse Spark returns a box itself.
evidence.png and segment.json always say which model produced the box.
"""
import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import time
from contextlib import aclosing
from pathlib import Path

from dotenv import load_dotenv
from meta_sam_parser import parse_responses_stream, video_segmentation_format
from openai import AsyncOpenAI
from PIL import Image, ImageDraw

from backend.llm import chat

load_dotenv()

MODEL = "sam-3.1"
FPS = 5
WIDTH = 1280
GENERIC_CONCEPTS = ["price", "button", "text field"]
PICK_PROMPT = Path(__file__).resolve().parent / "prompts" / "pick_box.md"
LOCATE_PROMPT = Path(__file__).resolve().parent / "prompts" / "locate_box.md"


def to_mp4(video: Path, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-an",
                    "-vf", f"fps={FPS},scale={WIDTH}:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    return out


def _client() -> AsyncOpenAI:
    key = os.getenv("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set in .env")
    return AsyncOpenAI(base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1"), api_key=key)


async def upload(mp4: Path) -> str:
    async with _client() as api:
        f = await api.files.create(file=(mp4.name, mp4.read_bytes(), "video/mp4"), purpose="user_data")
    return f.id


async def _events(stream, usage: dict):
    """SDK events -> plain dicts for the parser. The API sends response.content_part.done but not
    response.output_text.done, which the parser needs to close a lane, so synthesize it (as the
    cookbook does). Also captures usage from response.completed."""
    done = set()
    async for event in stream:
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        lane = (data.get("item_id"), data.get("output_index"), data.get("content_index"))
        if data.get("type") == "response.completed":
            usage.update((data.get("response") or {}).get("usage") or {})
        if data.get("type") == "response.output_text.done":
            if lane not in done:
                done.add(lane)
                yield data
            continue
        yield data
        part = data.get("part")
        if (data.get("type") == "response.content_part.done" and lane not in done and isinstance(part, dict)
                and part.get("type") == "output_text" and isinstance(part.get("text"), str)):
            done.add(lane)
            yield {"type": "response.output_text.done", "item_id": data.get("item_id"),
                   "output_index": data.get("output_index"), "content_index": data.get("content_index"),
                   "text": part["text"]}


async def segment_video(file_id: str, concept: str) -> tuple[list[dict], dict]:
    """Boxes [{object_id, frame, t, left, top, right, bottom, confidence}] and call info."""
    usage, started = {}, time.time()
    async with _client() as api:
        stream = await api.responses.create(model=MODEL, stream=True, input=[{
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": concept}, {"type": "input_video", "file_id": file_id}]}])
        async with stream, aclosing(_events(stream, usage)) as events:
            parsed = parse_responses_stream(events, video_segmentation_format())
            async with parsed:
                async for _ in parsed:
                    pass
                result = await parsed.final_result()
    if result.outcome.status != "completed":
        raise RuntimeError(f"SAM incomplete: {getattr(result.outcome, 'reason', '?')}")
    boxes = [{"object_id": r.object_id, "frame": r.frame.frame_index if r.frame else None,
              "t": r.frame.frame_index / FPS if r.frame else None,
              "left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom, "confidence": r.confidence}
             for r in result.records if r.kind == "box"]
    info = {"model": MODEL, "provider": "meta", "concept": concept, "media": result.media,
            "usage": usage, "latency_s": round(time.time() - started, 1),
            "errors": [d.message for d in result.diagnostics if d.severity == "error"]}
    return boxes, info


def boxes_near(boxes: list[dict], t: float) -> list[dict]:
    """Boxes on the SAM frame closest to time t."""
    timed = [b for b in boxes if b["t"] is not None]
    if not timed:
        return []
    nearest = min({b["t"] for b in timed}, key=lambda bt: abs(bt - t))
    return [b for b in timed if b["t"] == nearest]


def draw_evidence(frame_path: Path, boxes: list[dict], out: Path, label: str,
                  source_size: tuple[int, int] | None = None) -> Path:
    img = Image.open(frame_path).convert("RGB")
    sx = img.width / source_size[0] if source_size else 1.0
    sy = img.height / source_size[1] if source_size else 1.0
    draw = ImageDraw.Draw(img)
    for b in boxes:
        x0, y0, x1, y1 = b["left"] * sx, b["top"] * sy, b["right"] * sx, b["bottom"] * sy
        pad = 6
        draw.rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), outline=(230, 30, 60), width=4)
        draw.rectangle((x0 - pad, y0 - pad - 22, x0 - pad + 8 + 7 * len(label), y0 - pad), fill=(230, 30, 60))
        draw.text((x0 - pad + 4, y0 - pad - 19), label, fill="white")
    img.save(out)
    return out


def _jpeg_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def pick_box(frame_path: Path, boxes: list[dict], claim: dict) -> tuple[int, str, dict]:
    """Muse Spark picks which numbered SAM box is the claimed element."""
    img = Image.open(frame_path).convert("RGB")
    sx = img.width / WIDTH
    draw = ImageDraw.Draw(img)
    for i, b in enumerate(boxes):
        draw.rectangle((b["left"] * sx - 4, b["top"] * sx - 4, b["right"] * sx + 4, b["bottom"] * sx + 4),
                       outline=(230, 30, 60), width=3)
        draw.text((b["right"] * sx + 8, b["top"] * sx - 2), str(i), fill=(230, 30, 60))
    schema = {"type": "json_schema", "json_schema": {"name": "pick", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["index", "reason"],
        "properties": {"index": {"type": "integer", "enum": list(range(len(boxes)))}, "reason": {"type": "string"}}}}}
    text, meta = chat([{"role": "system", "content": PICK_PROMPT.read_text()}, {"role": "user", "content": [
        {"type": "text", "text": f"Element: {claim['element']}\nWhat it shows: {claim['actual']}"},
        {"type": "image_url", "image_url": {"url": _jpeg_url(img)}}]}],
        stage="evidence", effort="low", response_format=schema)
    out = json.loads(text)
    return out["index"], out["reason"], meta


def locate_box(frame_path: Path, claim: dict) -> tuple[dict, dict]:
    """Fallback when SAM finds nothing: Muse Spark returns the box in image pixels."""
    img = Image.open(frame_path).convert("RGB")
    coord = {"type": "integer", "minimum": 0, "maximum": 1000}
    schema = {"type": "json_schema", "json_schema": {"name": "box", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["left", "top", "right", "bottom"],
        "properties": {k: coord for k in ("left", "top", "right", "bottom")}}}}
    text, meta = chat([{"role": "system", "content": LOCATE_PROMPT.read_text()}, {"role": "user", "content": [
        {"type": "text", "text": f"Element: {claim['element']}\n"
                                 f"What it shows: {claim['actual']}"},
        {"type": "image_url", "image_url": {"url": _jpeg_url(img)}}]}],
        stage="evidence", effort="low", response_format=schema)
    # Coordinates come back on a 0-1000 scale per axis (asked for explicitly: pixel answers
    # had y on that scale anyway on a 1280x698 frame).
    box = json.loads(text)
    box = {k: v * (img.width if k in ("left", "right") else img.height) / 1000 for k, v in box.items()}
    return {**box, "object_id": "muse"}, meta


async def evidence(run_dir: Path, concepts: list[str] | None = None, use_sam: bool = True) -> dict:
    """SAM (+ Muse Spark pick) or Muse Spark fallback -> run_dir/evidence.png + segment.json."""
    steps = json.loads((run_dir / "steps.json").read_text())
    frames = json.loads((run_dir / "frames.json").read_text())
    claim = steps["bug_claim"]
    frame = next(f for f in frames["frames"] if f["n"] == claim["frame_ref"])
    frame_path = run_dir / frame["path"]
    concepts = concepts or [claim["element"]] + [c for c in GENERIC_CONCEPTS if c != claim["element"]]
    report = {"frame": frame, "tried": [], "calls": []}

    near = []
    if use_sam:
        mp4 = to_mp4(Path(frames["video"]), run_dir / "sam_input.mp4")
        file_id = await upload(mp4)
        for concept in concepts:
            boxes, info = await segment_video(file_id, concept)
            near = boxes_near(boxes, frame["t"])
            report["tried"].append({"concept": concept, "boxes": len(boxes), "on_bug_frame": len(near),
                                    "latency_s": info["latency_s"], "usage": info["usage"]})
            report["calls"].append(info)
            if near:
                report["concept"] = concept
                break

    if len(near) == 1:
        chosen, method = near[0], "SAM 3.1"
    elif near:
        i, reason, meta = pick_box(frame_path, near, claim)
        chosen, method = near[i], "SAM 3.1 + Muse Spark pick"
        report.update(candidates=near, picked=i, pick_reason=reason)
        report["calls"].append(meta)
    else:
        chosen, meta = locate_box(frame_path, claim)
        method = "Muse Spark box (SAM found nothing)" if use_sam else "Muse Spark box"
        report["calls"].append(meta)
        chosen["source_size"] = None

    img_w = Image.open(frame_path).width
    source = None if chosen.get("object_id") == "muse" else (WIDTH, round(WIDTH * Image.open(frame_path).height / img_w))
    draw_evidence(frame_path, [chosen], run_dir / "evidence.png", f"{claim['element']} · {method}", source)
    report.update(method=method, box=chosen, evidence="evidence.png")
    (run_dir / "segment.json").write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit('usage: python -m backend.segment runs/<name> [--concept "order total" ...] [--no-sam]')
    concepts = [args[i + 1] for i, a in enumerate(args) if a == "--concept"]
    r = asyncio.run(evidence(Path(args[0]), concepts or None, use_sam="--no-sam" not in args))
    for t in r["tried"]:
        print(f"  SAM '{t['concept']}': {t['boxes']} boxes, {t['on_bug_frame']} on bug frame, {t['latency_s']}s, "
              f"frames processed {t['usage'].get('video_frames_processed')}")
    if "picked" in r:
        print(f"  Muse Spark picked #{r['picked']} of {len(r['candidates'])}: {r['pick_reason']}")
    b = r["box"]
    print(f"{r['method']}: ({b['left']:.0f},{b['top']:.0f})-({b['right']:.0f},{b['bottom']:.0f}) -> {args[0]}/evidence.png")
