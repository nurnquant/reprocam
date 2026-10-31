"""neg_total: promo GLOW20 can be applied repeatedly and the total goes below $0."""
from playwright.sync_api import expect

from conftest import add_product_to_basket, money


def test_promo_applies_once_and_total_never_negative(open_store):
    page = open_store()
    add_product_to_basket(page, "linen-towels")  # $27.60

    for _ in range(2):
        page.get_by_test_id("promo-input").fill("GLOW20")
        page.get_by_test_id("promo-apply").click()

    expect(page.get_by_test_id("discount-total")).to_have_text("-$20.00")
    total = money(page.get_by_test_id("order-total").inner_text())
    assert total >= 0, f"order total went negative: {total:.2f}"
    expect(page.get_by_test_id("order-total")).to_have_text("$7.60")
