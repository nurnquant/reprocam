"""Bug 3: ZIP codes starting with 0 leave the "Place order" spinner spinning forever."""
import re

from playwright.sync_api import expect

from conftest import add_product_to_basket


def test_checkout_completes_for_zip_starting_with_zero(open_store):
    page = open_store()
    add_product_to_basket(page, "pebble-light")
    page.get_by_test_id("checkout-button").click()

    page.get_by_test_id("checkout-name").fill("Ada Tester")
    page.get_by_test_id("checkout-email").fill("ada@example.com")
    page.get_by_test_id("checkout-address").fill("12 Harbor Lane")
    page.get_by_test_id("checkout-city").fill("Cambridge")
    page.get_by_test_id("checkout-zip").fill("02139")
    page.get_by_test_id("place-order").click()

    expect(page.get_by_test_id("order-confirmation")).to_be_visible(timeout=8000)
    expect(page.get_by_test_id("order-number")).to_have_text(re.compile(r"^LL-\d{6}$"))
