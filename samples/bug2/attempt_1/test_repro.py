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
    # Recreate state: add the item to basket (recording starts with item already added)
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn, "add to basket should be visible").to_be_visible()
    add_btn.click()
    added_msg = page.get_by_test_id("added-message")
    expect(added_msg, "added message should appear after adding").to_be_visible()
    # Step 2: View basket link in added message
    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart, "view basket link should be visible").to_be_visible()
    view_cart.click()
    # Ensure cart page loaded
    cart = page.get_by_test_id("cart")
    expect(cart, "cart should be visible").to_be_visible()
    # Step 3: Decrease quantity button for Pebble Night Light in basket
    # Use generic qty-minus (only one line in cart)
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus, "decrease quantity button should be visible").to_be_visible()
    qty_minus.click()
    # Wait for basket emptied - badge count 0
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count, "basket badge should show 0 after removing only item").to_have_text("0")
    # Step 4: Checkout link in basket summary
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn, "checkout link should be visible").to_be_visible()
    checkout_btn.click()
    # Checkout page should show empty basket state with $0.00, not stale $18.50
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total, "checkout order total should be $0.00 after emptying basket, not stale $18.50").to_be_visible(timeout=8000)
    expect(checkout_total, "checkout order total should be $0.00 after emptying basket, not stale $18.50").to_have_text("$0.00")
