"""SAM 3.1: find the broken element on the bug frame -> evidence.png ("SAM proposes, Muse Spark decides").

    python -m backend.segment runs/bug1 [--concept "order total" --concept price ...] [--no-sam]

Request and stream handling are ported from the Meta cookbook (07_sam/01_api_basics/python/
sam_api.py): one noun phrase per Responses call to sam-3.1, parsed ONLY with meta_sam_parser.

Default: image mode, on the keyframe at bug_claim.frame_ref (1 frame per request).
SAM_VIDEO_TRACK=1: video mode instead (for a tracking animation later): the recording is
re-encoded at 5 fps / 1280 px, uploaded with purpose=user_data, and the boxes nearest the bug
frame's time are used. Every SAM request is logged to data/llm_calls.jsonl with frames processed.

SAM finds UI objects (buttons, prices) well but not meanings ("order total" returns nothing,
"price" returns every price). So:
  1. try the claim's element, then generic concepts, until SAM has boxes on the bug frame;
  2. one box -> done; several -> Muse Spark picks one from a numbered overlay;
  3. no boxes at all -> fallback: Muse Spark returns a box itself (0-1000 scale on both axes).
All boxes are in the bug frame's pixels. evidence.png and segment.json say which model drew it.
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
from meta_sam_parser import image_segmentation_format, parse_responses_stream, video_segmentation_format
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont, ImageStat

from backend.llm import chat, log_call

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


async def _sam(concept: str, media: dict, fmt) -> tuple[object, dict, float]:
    usage, started = {}, time.time()
    async with _client() as api:
        stream = await api.responses.create(model=MODEL, stream=True, input=[{
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": concept}, media]}])
        async with stream, aclosing(_events(stream, usage)) as events:
            parsed = parse_responses_stream(events, fmt)
            async with parsed:
                async for _ in parsed:
                    pass
                result = await parsed.final_result()
    if result.outcome.status != "completed":
        raise RuntimeError(f"SAM incomplete: {getattr(result.outcome, 'reason', '?')}")
    return result, usage, round(time.time() - started, 1)


def _log_sam(concept: str, mode: str, usage: dict, latency_s: float, boxes: int) -> dict:
    info = {"stage": "segment", "model": MODEL, "provider": "meta", "effort": None, "mode": mode,
            "concept": concept, "frames_processed": usage.get("video_frames_processed", 1 if mode == "image" else None),
            "boxes": boxes, "latency_s": latency_s, "cost_usd": None}
    log_call(info)
    return info


def _box(r, scale_x: float = 1.0, scale_y: float = 1.0, fps: int | None = None) -> dict:
    return {"object_id": r.object_id, "frame": r.frame.frame_index if r.frame else None,
            "t": r.frame.frame_index / fps if (r.frame and fps) else None,
            "left": r.left * scale_x, "top": r.top * scale_y, "right": r.right * scale_x,
            "bottom": r.bottom * scale_y, "confidence": r.confidence}


async def segment_image(frame_path: Path, concept: str) -> tuple[list[dict], dict]:
    """Boxes in the frame's pixels, and the logged call info."""
    url = "data:image/jpeg;base64," + base64.b64encode(frame_path.read_bytes()).decode()
    result, usage, latency = await _sam(concept, {"type": "input_image", "image_url": url}, image_segmentation_format())
    boxes = [_box(r) for r in result.records if r.kind == "box"]
    return boxes, _log_sam(concept, "image", usage, latency, len(boxes))


async def segment_video(file_id: str, concept: str, frame_size: tuple[int, int]) -> tuple[list[dict], dict]:
    """Boxes for every tracked frame, scaled to frame_size (the keyframes' pixels)."""
    result, usage, latency = await _sam(concept, {"type": "input_video", "file_id": file_id},
                                        video_segmentation_format())
    sx = frame_size[0] / WIDTH
    boxes = [_box(r, sx, sx, FPS) for r in result.records if r.kind == "box"]
    return boxes, _log_sam(concept, "video", usage, latency, len(boxes))


def boxes_near(boxes: list[dict], t: float) -> list[dict]:
    """Boxes on the SAM frame closest to time t."""
    timed = [b for b in boxes if b["t"] is not None]
    if not timed:
        return []
    nearest = min({b["t"] for b in timed}, key=lambda bt: abs(bt - t))
    return [b for b in timed if b["t"] == nearest]


RED = (230, 30, 60)


def _blank(gray: Image.Image, rect: tuple[float, float, float, float], margin: int = 3) -> bool:
    """True if rect (plus a small margin) is inside the image and every pixel is within 12 grey
    levels of the area's median: no text, and no thin edges such as a panel border."""
    x0, y0, x1, y1 = (round(v) for v in rect)
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    if x0 < 0 or y0 < 0 or x1 > gray.width or y1 > gray.height:
        return False
    area = gray.crop((x0, y0, x1, y1))
    hist, half, seen = area.histogram(), area.width * area.height // 2, 0
    median = next(v for v in range(256) if (seen := seen + hist[v]) > half)
    lo, hi = ImageStat.Stat(area).extrema[0]
    return median - lo <= 12 and hi - median <= 12


def place_label(gray: Image.Image, box: tuple[float, float, float, float], size: tuple[int, int],
                gap: int = 8) -> tuple[float, float]:
    """Top-left corner for a label that covers no page text: above the box first, then beside or
    below it, then further out (e.g. outside the panel the element sits in)."""
    x0, y0, x1, y1 = box
    w, h = size
    cy = (y0 + y1) / 2 - h / 2
    near = [(x1 - w, y0 - gap - h), (x0, y0 - gap - h), (x1 + gap, cy), (x0 - gap - w, cy),
            (x1 - w, y1 + gap), (x0, y1 + gap)]
    for x, y in near:
        if _blank(gray, (x, y, x + w, y + h)):
            return x, y
    for d in range(gap + 16, max(gray.width, gray.height), 16):  # widen the search: outside the panel
        for x, y in [(x1 + d, cy), (x0 - d - w, cy), (x1 - w, y0 - d - h), (x1 - w, y1 + d)]:
            if _blank(gray, (x, y, x + w, y + h)):
                return x, y
    return max(0, x1 - w), max(0, y0 - gap - h)  # nothing blank: least bad, still above the box


def draw_evidence(frame_path: Path, box: dict, out: Path, label: str) -> Path:
    img = Image.open(frame_path).convert("RGB")
    gray = img.convert("L")
    draw = ImageDraw.Draw(img)
    pad = 6
    rect = (box["left"] - pad, box["top"] - pad, box["right"] + pad, box["bottom"] + pad)
    font = ImageFont.load_default(size=15)
    tx0, ty0, tx1, ty1 = draw.textbbox((0, 0), label, font=font)
    w, h = tx1 - tx0 + 12, ty1 - ty0 + 10
    lx, ly = place_label(gray, rect, (w, h))

    draw.rectangle(rect, outline=RED, width=4)
    # leader line when the label is not touching the box
    if not (rect[0] - w - 10 <= lx <= rect[2] + 10 and rect[1] - h - 10 <= ly <= rect[3] + 10):
        cx = min(max(lx + w / 2, rect[0]), rect[2])
        draw.line((lx + w / 2, ly + h / 2, cx, rect[1] if ly < rect[1] else rect[3]), fill=RED, width=2)
    draw.rectangle((lx, ly, lx + w, ly + h), fill=RED)
    draw.text((lx + 6 - tx0, ly + 5 - ty0), label, fill="white", font=font)
    img.save(out)
    return out


def _jpeg_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def pick_box(frame_path: Path, boxes: list[dict], claim: dict) -> tuple[int, str, dict]:
    """Muse Spark picks which numbered SAM box is the claimed element."""
    img = Image.open(frame_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    for i, b in enumerate(boxes):
        draw.rectangle((b["left"] - 4, b["top"] - 4, b["right"] + 4, b["bottom"] + 4), outline=RED, width=3)
        draw.text((b["right"] + 8, b["top"] - 3), str(i), fill=RED, font=font)
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
    """Fallback when SAM finds nothing: Muse Spark returns a box (0-1000 scale), converted to pixels."""
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

    video_mode = os.getenv("SAM_VIDEO_TRACK") == "1"
    report["sam_mode"] = "video" if video_mode else "image"
    near = []
    if use_sam:
        if video_mode:
            size = Image.open(frame_path).size
            file_id = await upload(to_mp4(Path(frames["video"]), run_dir / "sam_input.mp4"))
        for concept in concepts:
            if video_mode:
                boxes, info = await segment_video(file_id, concept, size)
                report.setdefault("tracks", {})[concept] = boxes  # every frame, for an animation later
                near = boxes_near(boxes, frame["t"])
            else:
                near, info = await segment_image(frame_path, concept)
            report["tried"].append({**info, "on_bug_frame": len(near)})
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

    draw_evidence(frame_path, chosen, run_dir / "evidence.png", f"{claim['element']} · {method}")
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
              f"{t['mode']} mode, frames processed {t['frames_processed']}")
    if "picked" in r:
        print(f"  Muse Spark picked #{r['picked']} of {len(r['candidates'])}: {r['pick_reason']}")
    b = r["box"]
    print(f"{r['method']}: ({b['left']:.0f},{b['top']:.0f})-({b['right']:.0f},{b['bottom']:.0f}) -> {args[0]}/evidence.png")
