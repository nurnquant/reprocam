"""Training-only bugs (M9): present only with ?train=1 on the buggy build.

test_training_* assert correct behaviour with ?train=1: they fail on the buggy build and pass on
the fixed one, like the demo-bug tests. test_public_store_* run WITHOUT ?train=1 on the buggy
build and must always pass: the public store shows only the 3 demo bugs.
"""
import re

import pytest
from playwright.sync_api import expect

from conftest import APP_URL, STORE_MODE, add_product_to_basket


def go(page, path="index.html", train=True, fixed=None):
    fixed = ("1" if STORE_MODE == "fixed" else "0") if fixed is None else fixed
    page.goto(f"{APP_URL}/{path}?fixed={fixed}&train={'1' if train else '0'}&reset=1")


def basket_with_two(page):
    add_product_to_basket(page, "linen-towels")  # $27.60
    page.get_by_test_id("nav-home").click()
    add_product_to_basket(page, "pebble-light")  # $18.50


def checkout(page, zip_code="10001"):
    page.get_by_test_id("checkout-button").click()
    for testid, value in (("checkout-name", "Ada Tester"), ("checkout-email", "ada@example.com"),
                          ("checkout-address", "12 Harbor Lane"), ("checkout-city", "Albany"), ("checkout-zip", zip_code)):
        page.get_by_test_id(testid).fill(value)
    page.get_by_test_id("place-order").click()
    expect(page.get_by_test_id("order-confirmation")).to_be_visible(timeout=8000)


# --- each training bug: fails on buggy (train=1), passes on fixed --------------------------------

def check_count_after_remove(page):
    basket_with_two(page)
    page.get_by_test_id("cart-line-linen-towels").get_by_test_id("line-remove").click()
    expect(page.get_by_test_id("cart-count"), "badge counts the one line left").to_have_text("1")


def check_subtotal_rounding(page):
    add_product_to_basket(page, "linen-towels")
    plus = page.get_by_test_id("cart-line-linen-towels").get_by_test_id("qty-plus")
    plus.click()
    plus.click()  # quantity 3
    expect(page.get_by_test_id("cart-subtotal"), "3 x $27.60").to_have_text("$82.80")


def check_detail_price(page):
    page.get_by_test_id("product-card-indigo-cushion").click()
    expect(page.get_by_test_id("product-detail").get_by_test_id("product-price"), "same as the list").to_have_text("$32.00")


def check_confirm_total_zero(page):
    add_product_to_basket(page, "pebble-light")
    checkout(page)
    expect(page.get_by_test_id("confirmation-total"), "charged the basket total").to_have_text("$18.50")


def check_remove_wrong_line(page):
    basket_with_two(page)
    page.get_by_test_id("cart-line-pebble-light").get_by_test_id("line-remove").click()
    expect(page.get_by_test_id("cart-line-linen-towels"), "the other line stays").to_be_visible()
    expect(page.get_by_test_id("cart-line-pebble-light"), "the clicked line goes").to_have_count(0)


CHECKS = [check_count_after_remove, check_subtotal_rounding, check_detail_price, check_confirm_total_zero,
          check_remove_wrong_line]


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__.removeprefix("check_"))
def test_training_bug(page, check):
    go(page, train=True)
    check(page)


# --- the public store (no ?train=1) never shows a training bug, even on the buggy build ----------

@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__.removeprefix("check_"))
def test_public_store_hides_training_bug(page, check):
    go(page, train=False, fixed="0")
    check(page)


def test_public_store_still_has_the_demo_bugs(page):
    go(page, train=False, fixed="0")
    expect(page.get_by_test_id("build-mode")).to_have_text(re.compile("buggy"))
    add_product_to_basket(page, "linen-towels")
    for _ in range(2):
        page.get_by_test_id("promo-input").fill("GLOW20")
        page.get_by_test_id("promo-apply").click()
    expect(page.get_by_test_id("order-total")).to_have_text("-$12.40")  # neg_total is still there
