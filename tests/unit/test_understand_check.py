"""The 'steps correct' checks used to measure understanding stability."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from understand_stability import check  # noqa: E402


def s(*acts, shows_app=True):
    return {"shows_app": shows_app, "steps": [{"action": a, "selector_hint": h, "value": v} for a, h, v in acts]}


def test_bug2_remove_is_wrong_minus_is_right():
    minus = s(("goto", None, "product.html?id=pebble-light"), ("click", "qty-minus", None), ("click", "checkout-button", None))
    remove = s(("goto", None, "product.html"), ("click", "view-cart", None), ("click", "line-remove", None))
    assert check("bug2", minus)[0] and not check("bug2", remove)[0]   # the live misread from the bug bash


def test_bug1_needs_two_applies_and_bug3_a_zero_zip():
    once = s(("fill", "promo-input", "GLOW20"), ("click", "promo-apply", None))
    twice = s(*[("fill", "promo-input", "GLOW20"), ("click", "promo-apply", None)] * 2)
    assert not check("bug1", once)[0] and check("bug1", twice)[0]
    assert check("bug3", s(("fill", "checkout-zip", "02139"), ("click", "place-order", None)))[0]
    assert not check("bug3", s(("fill", "checkout-zip", "12139"), ("click", "place-order", None)))[0]
    assert not check("bug3", s(("fill", "checkout-zip", "02139"), ("click", "place-order", None), shows_app=False))[0]
