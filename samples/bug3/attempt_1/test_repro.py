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
    expect(page.get_by_test_id("product-detail")).to_be_visible()
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    page.goto(url("cart.html"))
    expect(page.get_by_test_id("cart")).to_be_visible()
    expect(page.get_by_test_id("cart-count")).to_have_text("1")
    cart_line = page.get_by_test_id("cart-line-linen-towels")
    # If the cart line is for pebble-light variant, fallback to generic locators
    # The tester had Pebble Night Light in cart; locate by generic testids inside cart
    pebble_line = page.get_by_test_id("cart")
    # Increase quantity
    page.get_by_test_id("cart").get_by_test_id("qty-plus").click()
    # Decrease quantity
    page.get_by_test_id("cart").get_by_test_id("qty-minus").click()
    page.get_by_test_id("cart").get_by_test_id("qty-minus").click()
    # After decreases, quantity may be 0 and item removed or stay at 1 depending on implementation;
    # Ensure we have an item to checkout - if cart empty, re-add
    if page.get_by_test_id("cart-count").inner_text().strip() == "0":
        page.goto(url("product.html", id="pebble-light"))
        page.get_by_test_id("add-to-cart").click()
        expect(page.get_by_test_id("added-message")).to_be_visible()
        page.goto(url("cart.html"))
        expect(page.get_by_test_id("cart")).to_be_visible()
    page.get_by_test_id("checkout-button").click()
    expect(page.get_by_test_id("checkout-form")).to_be_visible()
    page.get_by_test_id("checkout-name").fill("Ada Tester")
    page.get_by_test_id("checkout-email").fill("ada@example.com")
    page.get_by_test_id("checkout-address").fill("12 harfpur lane")
    page.get_by_test_id("checkout-city").fill("Cambridge")
    page.get_by_test_id("checkout-zip").fill("02139")
    page.get_by_test_id("place-order").click()
    expect(page.get_by_test_id("order-confirmation"), "Clicking Place order should submit the checkout and navigate to order confirmation").to_be_visible(timeout=8000)
