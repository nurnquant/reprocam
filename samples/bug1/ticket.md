# Promo code GLOW20 can be applied repeatedly, stacking the $20 discount and driving the total negative.

**Status:** REPRODUCED · verified against known-good build
**Known-good build:** fixed build (?fixed=1): test passes
**App:** http://localhost:5173 · **Run:** `bug1-1793475489` · **Attempts:** 1

## Steps to reproduce
1. **goto** home page `index.html`
2. **click** Linen Tea Towels product card
3. **click** Add to basket button on product page
4. **click** View basket link after adding to basket
5. **fill** Promo code input field `GLOW20`
6. **click** Apply button in promo form
7. **fill** Promo code input field `GLOW20`
8. **click** Apply button in promo form

## Expected
Applying the same promo code a second time should have no additional effect; discount should remain -$20.00 and total should stay $7.60.

## Actual
Second apply stacked the discount to -$40.00 and changed the total to -$12.40 (shows "GLOW20 applied: $20.00 off." with Total -$12.40).

## Evidence
![order total](evidence.png)
*order total, frame 12 of the recording. Box: SAM 3.1 + Muse Spark pick.*

## Failing test
Fails on the buggy build with `builtins.AssertionError`:
```
discount should remain -$20.00 after second apply of same code
Expected value: '-$20.00'
Actual value: -$40.00
```
Judge (model): Test applied GLOW20 twice as claimed and asserted discount-total should remain '-$20.00'; failure shows '-$40.00' which matches the claimed stacking bug (-$40.00 / -$12.40 total).

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
```

Run it: `APP_URL=<app> REPRO_FIXED=0 pytest test_repro.py` (`REPRO_FIXED=1` on the practice store's fixed build).

*Filed by ReproCam · models: accounts/fireworks/models/muse-spark-open, muse-voice-transcribe-1.0, sam-3.1*
