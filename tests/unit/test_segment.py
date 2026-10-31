"""Evidence label placement: the label never covers page text or edges."""
from PIL import Image, ImageDraw

from backend.segment import _blank, place_label


def _page():
    """Light page with a text line directly above the box and a panel border to its right."""
    img = Image.new("L", (800, 400), 240)
    d = ImageDraw.Draw(img)
    d.rectangle((300, 150, 420, 160), fill=40)   # text right above the box
    d.line((470, 0, 470, 400), fill=215)         # faint panel border
    return img


def test_label_skips_text_above_the_box_and_the_panel_border():
    page, box, size = _page(), (360, 175, 420, 195), (200, 24)
    x, y = place_label(page, box, size)
    assert _blank(page, (x, y, x + size[0], y + size[1]))
    assert not (x < 470 < x + size[0]), "label straddles the panel border"


def test_label_goes_above_the_box_when_there_is_room():
    page = Image.new("L", (800, 400), 240)
    x, y = place_label(page, (360, 175, 420, 195), (200, 24))
    assert y + 24 <= 175  # above
