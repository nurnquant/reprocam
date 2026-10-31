# Hand check: 10 generated tests from the effort test

Picked at random (seed 20261031) from all 47 test attempts in the 27 current effort-test runs
(`runs/sweep/`, local only). For each: does the test check what the bug claim says, and is the judge's
verdict right? Every test starts with the same preamble (APP_URL, FIXED and the `url()` helper), shown once:

```python
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Page, expect

APP_URL = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")
FIXED = os.environ.get("REPRO_FIXED", "0")
EXTRA = dict(parse_qsl(os.environ.get("REPRO_QUERY", "")))  # flags for the app under test, set by the runner


def url(path, **params):
    """APP_URL + path, with query params merged in. The build flag fixed=FIXED is always set."""
    parts = urlsplit(f"{APP_URL}/{path.lstrip('/')}")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(EXTRA)
    query.update({k: str(v) for k, v in params.items()})
    query["fixed"] = FIXED
    return urlunsplit(parts._replace(query=urlencode(query)))
```

## 1. bug1 · effort low · run 3 · attempt_1

**Claim:** Promo code GLOW20 can be applied repeatedly, stacking the $20 discount and driving the total negative.  
**Expected:** Applying the same promo code a second time should have no additional effect; discount should remain -$20.00 and total should stay $7.60.

```python
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
    expect(page.get_by_test_id("add-to-cart")).to_be_visible()
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    page.get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    expect(page.get_by_test_id("cart-subtotal")).to_have_text("$27.60")
    # First apply of GLOW20
    page.get_by_test_id("promo-input").fill("GLOW20")
    page.get_by_test_id("promo-apply").click()
    expect(page.get_by_test_id("promo-message")).to_contain_text("GLOW20 applied")
    expect(page.get_by_test_id("discount-total"), "discount should be -$20.00 after first apply").to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total"), "total should be $7.60 after first apply").to_have_text("$7.60")
    # Second apply of same code - should have no additional effect
    page.get_by_test_id("promo-input").fill("GLOW20")
    page.get_by_test_id("promo-apply").click()
    expect(page.get_by_test_id("promo-message")).to_be_visible()
    expect(page.get_by_test_id("discount-total"), "discount should remain -$20.00 after second apply of same code").to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total"), "total should remain $7.60 after second apply, not stack to negative").to_have_text("$7.60")
```

- **Buggy build:** assert_fail: discount should remain -$20.00 after second apply of same code | Expected value: '-$20.00' | Actual value: -$40.00
- **Known-good build:** pass
- **Judge (model):** REPRODUCED: Test reapplies GLOW20 and the failing assertion shows discount stacked to -$40.00 instead of staying -$20.00, exactly the symptom described in the claim.
- **Run ended:** REPRODUCED · verified against known-good build (attempt 1 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 2. bug1 · effort medium · run 1 · attempt_2

**Claim:** Promo code GLOW20 can be applied repeatedly, stacking the $20 discount and driving the total negative.  
**Expected:** Applying the same promo code a second time should have no additional effect; discount should remain -$20.00 and total should stay $7.60.

```python
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
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("view-cart")).to_be_visible()
    page.get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    # first apply of GLOW20
    page.get_by_test_id("promo-form").get_by_test_id("promo-input").fill("GLOW20")
    page.get_by_test_id("promo-form").get_by_test_id("promo-apply").click()
    expect(page.get_by_test_id("promo-message")).to_be_visible()
    expect(page.get_by_test_id("discount-total")).to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total")).to_have_text("$7.60")
    # second apply of same code should have no additional effect
    page.get_by_test_id("promo-form").get_by_test_id("promo-input").fill("GLOW20")
    page.get_by_test_id("promo-form").get_by_test_id("promo-apply").click()
    # wait for promo handling to settle
    expect(page.get_by_test_id("promo-message")).to_be_visible()
    expect(page.get_by_test_id("discount-total"), "discount should remain -$20.00 after second apply of same promo code").to_have_text("-$20.00")
    expect(page.get_by_test_id("order-total"), "total should stay $7.60 after second apply of same promo code").to_have_text("$7.60")
    expect(page.get_by_test_id("cart-subtotal"), "subtotal should remain $27.60").to_have_text("$27.60")
```

- **Buggy build:** assert_fail: discount should remain -$20.00 after second apply of same promo code | Expected value: '-$20.00' | Actual value: -$40.00
- **Known-good build:** pass
- **Judge (model):** REPRODUCED: Test correctly reproduces two sequential applies of GLOW20 and fails on discount-total assertion expecting -$20.00 but observing -$40.00, matching the claimed stacking symptom.
- **Run ended:** REPRODUCED · verified against known-good build (attempt 2 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 3. bug2 · effort high · run 1 · attempt_1

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
def test_reproduces_bug(page: Page):
    page.goto(url("product.html", id="pebble-light"))
    expect(page.get_by_test_id("product-detail")).to_be_visible()
    # Recreate state that was present in first frame: item must be in basket for "View basket" link to exist
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    expect(page.get_by_test_id("cart-count")).to_have_text("1")
    # Tester step: click View basket link in added message
    page.get_by_test_id("added-message").get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    pebble_line = page.get_by_test_id("cart-line-pebble-light")
    expect(pebble_line).to_be_visible()
    expect(pebble_line.get_by_test_id("line-qty")).to_have_text("1")
    expect(pebble_line.get_by_test_id("line-total")).to_have_text("$18.50")
    expect(page.get_by_test_id("order-total")).to_have_text("$18.50")
    # Tester step: Decrease quantity button for Pebble Night Light in basket (empties basket)
    pebble_line.get_by_test_id("qty-minus").click()
    expect(page.get_by_test_id("cart-count"), "basket badge should be 0 after removing only item").to_have_text("0", timeout=8000)
    # Tester step: Checkout link in basket summary
    page.get_by_test_id("checkout-button").click()
    expect(page.get_by_test_id("checkout-form")).to_be_visible(timeout=8000)
    # Bug: badge 0 but checkout Order total still shows $18.50
    expect(page.get_by_test_id("checkout-total"), "checkout total should be $0.00 when basket is empty, not stale $18.50").to_have_text("$0.00")
```

- **Buggy build:** assert_fail: checkout total should be $0.00 when basket is empty, not stale $18.50 | Expected value: '$0.00' | Actual value: $18.50
- **Known-good build:** assert_fail: basket badge should be 0 after removing only item | Expected value: '0' | Actual value: 1
- **Judge (model):** REPRODUCED: Test emptied basket via qty-minus (cart-count 0) then checked checkout-total for $0.00; failure shows $18.50 which exactly matches the claimed stale Order total symptom.
- **Run ended:** REPRODUCED · verified against known-good build (attempt 2 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 4. bug2 · effort high · run 2 · attempt_3

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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

    # Recreate pre-state: product page already has "Added to basket" in recording, so add item first
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn).to_be_visible()
    add_btn.click()

    added = page.get_by_test_id("added-message")
    expect(added).to_be_visible()

    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart).to_be_visible()
    view_cart.click()

    cart = page.get_by_test_id("cart")
    expect(cart).to_be_visible()

    line = page.get_by_test_id("cart-line-pebble-light")
    expect(line).to_be_visible()

    qty_minus = line.get_by_test_id("qty-minus")
    expect(qty_minus).to_be_visible()
    qty_minus.click()

    # After removing the only item basket should be empty
    badge = page.get_by_test_id("nav-cart").get_by_test_id("cart-count")
    expect(badge, "badge should show 0 after removing last item").to_have_text("0")

    # Tester then goes to checkout via basket summary link
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn).to_be_visible()
    checkout_btn.click()

    # Buggy build keeps stale $18.50, fixed build shows empty $0.00
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total).to_be_visible(timeout=8000)
    expect(checkout_total, "checkout total should be $0.00 after emptying basket, not stale $18.50").to_have_text("$0.00")
```

- **Buggy build:** assert_fail: checkout total should be $0.00 after emptying basket, not stale $18.50 | Expected value: '$0.00' | Actual value: $18.50
- **Known-good build:** assert_fail: badge should show 0 after removing last item | Expected value: '0' | Actual value: 1
- **Judge (model):** REPRODUCED: Test correctly emptied basket (badge 0) then checked checkout total for $0.00 but got stale $18.50, matching the claimed symptom exactly at expect(checkout_total).to_have_text("$0.00").
- **Run ended:** REPRODUCED · NOT CONFIRMED (also fails on fixed build) (attempt 3 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 5. bug2 · effort high · run 3 · attempt_2

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    # Recreate state seen in first frame: item added to basket
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    expect(page.get_by_test_id("cart-count")).to_have_text("1")
    # Step 2: View basket link in added message
    page.get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    expect(page.get_by_test_id("cart-count")).to_have_text("1")
    # Step 3: Decrease quantity button for Pebble Night Light in basket (single item)
    page.get_by_test_id("cart").get_by_test_id("qty-minus").click()
    # On the fixed build minus on qty 1 does not empty the basket - count stays 1, keeping cart and checkout consistent
    expect(page.get_by_test_id("cart-count"), "basket count should remain 1 after decreasing single-item quantity; minus should not empty basket").to_have_text("1")
    # Step 4: Checkout link in basket summary
    page.get_by_test_id("checkout-button").click()
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total).to_be_visible(timeout=8000)
    expect(checkout_total, "checkout total should match basket count of 1 item at $18.50").to_have_text("$18.50")
```

- **Buggy build:** assert_fail: basket count should remain 1 after decreasing single-item quantity; minus should not empty basket | Expected value: '1' | Actual value: 0
- **Known-good build:** pass
- **Judge (model):** NOT_REPRODUCED: Failure is on the inverted assertion expecting cart-count "1" after qty-minus (got "0") while the claim's expected is count 0 with checkout $0.00/empty; the test also expects the buggy $18.50 checkout total as correct and never checks empty-state behavior.
- **Run ended:** REPRODUCED · NOT CONFIRMED (also fails on fixed build) (attempt 3 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 6. bug2 · effort low · run 1 · attempt_1

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    # Setup: add the item to create the pre-condition seen in recording
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn, "add to basket button should be visible").to_be_visible()
    add_btn.click()
    added_msg = page.get_by_test_id("added-message")
    expect(added_msg, "added message should appear after adding").to_be_visible()
    # Step 2: View basket link in added message
    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart, "view basket link should be visible").to_be_visible()
    view_cart.click()
    cart = page.get_by_test_id("cart")
    expect(cart, "cart should be visible").to_be_visible()
    # Verify cart has item before decreasing
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count, "basket should have 1 item before decreasing").to_have_text("1")
    # Step 3: Decrease quantity to empty basket (1 -> 0)
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus, "decrease quantity button should be visible").to_be_visible()
    qty_minus.click()
    # Basket should now be empty
    expect(cart_count, "basket badge should show 0 after removing only item").to_have_text("0")
    # Step 4: Checkout link in basket summary
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn, "checkout button should be visible").to_be_visible()
    checkout_btn.click()
    checkout_form = page.get_by_test_id("checkout-form")
    expect(checkout_form, "checkout form should be visible").to_be_visible()
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total, "checkout total should be visible").to_be_visible()
    # After emptying basket, order total must be $0.00 and not stale $18.50
    expect(checkout_total, "checkout total should be $0.00 after emptying basket, not stale $18.50").to_have_text(re.compile(r"\\$0\\.00"))
```

- **Buggy build:** assert_fail: checkout total should be $0.00 after emptying basket, not stale $18.50 | Expected value: 're.compile('\\\\$0\\\\.00')' | Actual value: $18.50
- **Known-good build:** assert_fail: basket badge should show 0 after removing only item | Expected value: '0' | Actual value: 1
- **Judge (model):** REPRODUCED: Test correctly empties basket (badge 0) then checks checkout-total for $0.00; failure shows $18.50 which exactly matches claim's actual stale total.
- **Run ended:** REPRODUCED · verified against known-good build (attempt 2 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 7. bug2 · effort low · run 1 · attempt_2

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn, "add to basket button should be visible").to_be_visible()
    add_btn.click()
    added_msg = page.get_by_test_id("added-message")
    expect(added_msg, "added message should appear after adding").to_be_visible()
    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart, "view basket link should be visible").to_be_visible()
    view_cart.click()
    cart = page.get_by_test_id("cart")
    expect(cart, "cart should be visible").to_be_visible()
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count, "basket should have 1 item before decreasing").to_have_text("1")
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus, "decrease quantity button should be visible").to_be_visible()
    qty_minus.click()
    # Do not assert badge becomes 0; known-good keeps it at 1, buggy goes to 0.
    # Go to checkout via checkout button
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn, "checkout button should be visible").to_be_visible()
    checkout_btn.click()
    checkout_form = page.get_by_test_id("checkout-form")
    expect(checkout_form, "checkout form should be visible").to_be_visible()
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total, "checkout total should be visible").to_be_visible()
    # Consistency check: checkout total must agree with basket count (1 * $18.50 or 0 * $18.50)
    # Read count to determine expected total, but keep assertion message static.
    count_text = cart_count.inner_text().strip()
    try:
        count_val = int(count_text)
    except ValueError:
        count_val = 1
    price = 18.50
    expected_val = count_val * price
    expected_str = f"${expected_val:.2f}"
    expect(checkout_total, "checkout order total should be consistent with basket count (stale total bug)").to_have_text(expected_str)
```

- **Buggy build:** assert_fail: checkout order total should be consistent with basket count (stale total bug) | Expected value: '$0.00' | Actual value: $18.50
- **Known-good build:** pass
- **Judge (model):** REPRODUCED: Test decreased quantity to empty basket (cart-count read as 0 -> expected $0.00) and asserting checkout-total failed showing $18.50, exactly matching claim that badge is 0 but order total stale at $18.50.
- **Run ended:** REPRODUCED · verified against known-good build (attempt 2 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 8. bug2 · effort low · run 2 · attempt_1

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    # produce the added state seen in first frame: add item to basket
    expect(page.get_by_test_id("product-detail")).to_be_visible()
    page.get_by_test_id("add-to-cart").click()
    expect(page.get_by_test_id("added-message")).to_be_visible()
    # step 2: View basket link in added message
    page.get_by_test_id("view-cart").click()
    expect(page.get_by_test_id("cart")).to_be_visible()
    expect(page.get_by_test_id("cart-count")).to_have_text("1")
    # step 3: Decrease quantity for Pebble Night Light to empty basket
    page.get_by_test_id("qty-minus").click()
    # basket should be emptied
    expect(page.get_by_test_id("cart-count"), "basket badge should show 0 after removing only item").to_have_text("0")
    # step 4: Checkout link in basket summary
    page.get_by_test_id("checkout-button").click()
    expect(page.get_by_test_id("checkout-form")).to_be_visible()
    # checkout should reflect empty basket, not stale $18.50
    expect(page.get_by_test_id("checkout-total"), "checkout total should be $0.00 when basket is empty and not show stale $18.50").to_have_text("$0.00")
```

- **Buggy build:** assert_fail: checkout total should be $0.00 when basket is empty and not show stale $18.50 | Expected value: '$0.00' | Actual value: $18.50
- **Known-good build:** assert_fail: basket badge should show 0 after removing only item | Expected value: '0' | Actual value: 1
- **Judge (model):** REPRODUCED: Test followed reported steps (add item, decrement to 0, checkout) and assertion on checkout-total failed with $18.50 vs expected $0.00, matching the claimed stale total symptom.
- **Run ended:** REPRODUCED · NOT CONFIRMED (also fails on fixed build) (attempt 3 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 9. bug2 · effort low · run 3 · attempt_2

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count, "basket should show 1 item before decreasing").to_have_text("1")
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus, "decrease quantity button should be visible").to_be_visible()
    qty_minus.click()
    # Correct behavior: quantity should not go below 1 via minus, basket stays 1; buggy build empties to 0
    expect(cart_count, "basket badge should remain 1 after decreasing single item quantity - should not empty to 0").to_have_text("1")
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn, "checkout button should be visible").to_be_visible()
    checkout_btn.click()
    checkout_form = page.get_by_test_id("checkout-form")
    expect(checkout_form, "checkout form should be visible").to_be_visible()
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total, "checkout total should be visible").to_be_visible()
    # When basket has 1 item, checkout total should match that item's price and not be stale/zero
    expect(checkout_total, "checkout order total should equal basket contents $18.50 for 1 item").to_have_text("$18.50")
```

- **Buggy build:** assert_fail: basket badge should remain 1 after decreasing single item quantity - should not empty to 0 | Expected value: '1' | Actual value: 0
- **Known-good build:** pass
- **Judge (model):** NOT_REPRODUCED: Failing assertion is on cart-count expecting '1' not on the claimed 'order total' element; test asserts basket should NOT empty to 0 and aborts before checking checkout-total for stale $18.50, so it does not verify the expected empty $0.00 state.
- **Run ended:** REPRODUCED · NOT CONFIRMED (also fails on fixed build) (attempt 3 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

## 10. bug2 · effort medium · run 2 · attempt_2

**Claim:** Basket emptied to 0 after decreasing quantity but checkout page still shows previous order total.  
**Expected:** After removing the only item, checkout should show empty basket state with order total $0.00 (or empty) and not allow checkout with stale amount.

```python
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
    # Pre-condition: add the item so the "Added to your basket. View basket" message is visible as in step 1
    add_btn = page.get_by_test_id("add-to-cart")
    expect(add_btn).to_be_visible(timeout=8000)
    add_btn.click()
    added_msg = page.get_by_test_id("added-message")
    expect(added_msg).to_be_visible(timeout=8000)
    # Step 2: View basket link in added message
    view_cart = page.get_by_test_id("view-cart")
    expect(view_cart).to_be_visible()
    view_cart.click()
    cart = page.get_by_test_id("cart")
    expect(cart).to_be_visible(timeout=8000)
    # Step 3: Decrease quantity button for the item in basket
    qty_minus = page.get_by_test_id("qty-minus")
    expect(qty_minus).to_be_visible(timeout=8000)
    qty_minus.click()
    # Let basket state settle - badge is visible
    cart_count = page.get_by_test_id("cart-count")
    expect(cart_count).to_be_visible(timeout=8000)
    # Give UI time to update cart totals after decrease (max 2s)
    page.wait_for_timeout(500)
    count_text = cart_count.inner_text().strip()
    # Step 4: Checkout link in basket summary
    checkout_btn = page.get_by_test_id("checkout-button")
    expect(checkout_btn).to_be_visible(timeout=8000)
    checkout_btn.click()
    checkout_form = page.get_by_test_id("checkout-form")
    expect(checkout_form).to_be_visible(timeout=8000)
    checkout_total = page.get_by_test_id("checkout-total")
    expect(checkout_total).to_be_visible(timeout=8000)
    # The checkout total must agree with the basket badge. For Pebble Night Light unit price is $18.50.
    # On the buggy build badge becomes 0 but checkout still shows $18.50 (inconsistent).
    # On the fixed build badge stays 1 and checkout shows $18.50 (consistent).
    if count_text == "0":
        expect(checkout_total, "basket is empty (0 items) so checkout order total should be $0.00, not stale $18.50").to_have_text("$0.00")
    else:
        expect(checkout_total, "basket has 1 item so checkout total should match 1 x $18.50").to_have_text("$18.50")
```

- **Buggy build:** assert_fail: basket is empty (0 items) so checkout order total should be $0.00, not stale $18.50 | Expected value: '$0.00' | Actual value: $18.50
- **Known-good build:** pass
- **Judge (model):** REPRODUCED: Test followed claim steps (add pebble-light, decrease qty to 0, go to checkout) and failing assertion directly checks the expected empty-basket total. Failure shows badge 0 but checkout-total is $18.50, exactly the stale amount described in the claim (tester saw $18.50, test observed $18.50).
- **Run ended:** REPRODUCED · verified against known-good build (attempt 2 of the run)

Your read: test checks the claim ☐ yes ☐ no · verdict right ☐ yes ☐ no · note:

