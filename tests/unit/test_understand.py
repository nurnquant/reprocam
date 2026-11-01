"""Offline parts of backend.understand: duplicate-frame filter and the output schema."""
from PIL import Image, ImageDraw

from backend.understand import distinct_frames, schema


def _frame(tmp_path, n, text=None, cursor=None):
    img = Image.new("RGB", (1280, 700), "white")
    draw = ImageDraw.Draw(img)
    if text:
        draw.rectangle((900, 400, 1100, 440), fill="black")  # e.g. a total that changed
    if cursor:
        draw.rectangle((cursor, 100, cursor + 6, 110), fill="black")  # a small moving cursor
    img.save(tmp_path / f"f{n}.jpg")
    return {"n": n, "t": float(n), "path": f"f{n}.jpg"}


def test_distinct_frames_drops_cursor_moves_but_keeps_ui_changes_and_last(tmp_path):
    frames = [
        _frame(tmp_path, 0),
        _frame(tmp_path, 1, cursor=200),  # cursor only: duplicate
        _frame(tmp_path, 2, text=True),   # UI change: keep
        _frame(tmp_path, 3, text=True),   # same: duplicate
        _frame(tmp_path, 4, text=True),   # same, but last: keep
    ]
    assert [f["n"] for f in distinct_frames(tmp_path, frames)] == [0, 2, 4]


def test_schema_limits_selectors_and_frames_to_what_exists():
    s = schema(["promo-apply", "order-total"], [0, 4, 9])["json_schema"]["schema"]
    step = s["properties"]["steps"]["items"]["properties"]
    assert step["selector_hint"]["enum"] == ["promo-apply", "order-total", None]
    assert step["frame_ref"]["enum"] == [0, 4, 9]
    assert s["properties"]["bug_claim"]["properties"]["frame_ref"]["enum"] == [0, 4, 9]


def test_frames_are_capped_for_providers_with_an_image_limit():
    from backend.understand import limit_frames
    frames = [{"n": i} for i in range(13)]
    changes = [None, 50, 900, 40, 700, 60, 30, 800, 45, 35, 600, 55, 70]
    kept = limit_frames(frames, changes, 8)
    assert [f["n"] for f in kept] == [0, 2, 4, 5, 7, 10, 11, 12]  # first, last, 6 biggest changes, in time order
    assert limit_frames(frames, changes, None) == frames and limit_frames(frames[:5], changes[:5], 8) == frames[:5]


def test_baseten_image_limit(monkeypatch):
    from backend.llm import image_limit
    assert image_limit("baseten") == 8 and image_limit("fireworks") is None
    monkeypatch.setenv("MAX_IMAGES_BASETEN", "6")
    assert image_limit("baseten") == 6
