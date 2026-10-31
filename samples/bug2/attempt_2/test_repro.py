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
    page.goto(url("product.html", id="pebble-light"))
    # Recreate state: add the single Pebble Night Light item
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn, "add to basket should be visible").to_be_visible()
    add_btn.click()
    added_msg = page.get_by_test_id("added-message")
    expect(added_msg, "added message should appear after adding").to_be_visible()
    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart, "view basket link should be visible").to_be_visible()
    view_cart.click()
    cart = page.get_by_test_id("cart")
    expect(cart, "cart should be visible").to_be_visible()
    # Tester decreased quantity for the single item
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus, "decrease quantity button should be visible").to_be_visible()
    qty_minus.click()
    # Allow state to settle (either clamped to 1 or emptied to 0)
    page.wait_for_timeout(500)
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn, "checkout link should be visible").to_be_visible()
    checkout_btn.click()
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total, "checkout total should be visible").to_be_visible(timeout=8000)
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count, "basket badge should be visible on checkout").to_be_visible()
    # Assert consistency between badge count and checkout total.
    # On correct build, a single item remains (1 x $18.50) so total is $18.50.
    # On buggy build badge goes to 0 but checkout still shows stale $18.50 - inconsistent.
    count_text = cart_count.inner_text().strip()
    if count_text == "0":
        expect(checkout_total, "checkout total should be $0.00 when basket is empty").to_have_text("$0.00")
    else:
        expect(checkout_total, "checkout total should match basket count (1 x $18.50)").to_have_text("$18.50")
