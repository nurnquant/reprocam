import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Page, expect

APP_URL = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")
FIXED = os.environ.get("REPRO_FIXED", "0")


def url(path, **params):
    """APP_URL + path, with query params merged in. The build flag fixed=FIXED is always set."""
    parts = urlsplit(f"{APP_URL}/{path.lstrip('/')}")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    query["fixed"] = FIXED
    return urlunsplit(parts._replace(query=urlencode(query)))


def test_reproduces_bug(page: Page):
    page.goto(url("index.html"))
    page.get_by_test_id("product-card-linen-towels").click()
    expect(page.get_by_test_id("product-detail")).to_be_visible()
    page.get_by_test_id("product-detail").get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    page.get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    promo_form = page.get_by_test_id("cart").get_by_test_id("promo-form")
    expect(promo_form).to_be_visible()
    promo_input = promo_form.get_by_test_id("promo-input")
    promo_apply = promo_form.get_by_test_id("promo-apply")
    promo_input.fill("GLOW20")
    promo_apply.click()
    expect(page.get_by_test_id("promo-message")).to_be_visible()
    expect(page.get_by_test_id("promo-message"), "promo message should confirm GLOW20 applied").to_contain_text("GLOW20 applied")
    expect(page.get_by_test_id("discount-total"), "discount should be -$20.00 after first apply").to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total"), "total should be $7.60 after first apply").to_have_text("$7.60")
    # Apply same code again - should have no additional effect
    promo_input.fill("GLOW20")
    promo_apply.click()
    # Wait for cart to settle - message should still be visible
    expect(page.get_by_test_id("promo-message")).to_be_visible()
    expect(page.get_by_test_id("discount-total"), "discount should remain -$20.00 after second apply of same code").to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total"), "total should remain $7.60 after second apply of same promo").to_have_text("$7.60")
