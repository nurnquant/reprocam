"""qty_stepper: "−" on quantity 1 sets the line to 0, but the line is still charged."""
from conftest import add_product_to_basket, money


def test_minus_at_one_never_charges_for_zero_items(open_store):
    page = open_store()
    add_product_to_basket(page, "linen-towels")  # $27.60

    line = page.get_by_test_id("cart-line-linen-towels")
    line.get_by_test_id("qty-minus").click()

    qty = int(line.get_by_test_id("line-qty").inner_text())
    charged = money(page.get_by_test_id("cart-subtotal").inner_text())
    assert qty >= 1, f"quantity dropped to {qty} but the basket still charges ${charged:.2f}"
    assert charged == round(qty * 27.60, 2), f"charged ${charged:.2f} for quantity {qty}"
