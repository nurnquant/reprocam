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
