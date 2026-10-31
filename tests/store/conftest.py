"""Ground-truth tests for the practice store.

Each test asserts the CORRECT behaviour, so it fails on the buggy build and passes on the
fixed one. Pick the build with STORE_MODE=buggy|fixed (default buggy). APP_URL overrides
the store address; if it points at localhost and nothing is listening, the store is
started for the test session.
"""
import os
import sys

import pytest
from playwright.sync_api import expect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from serve_store import store_running  # noqa: E402

APP_URL = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
STORE_MODE = os.getenv("STORE_MODE", "buggy")

expect.set_options(timeout=3000)


@pytest.fixture(scope="session", autouse=True)
def store_server():
    with store_running(APP_URL):
        yield


@pytest.fixture
def open_store(page):
    """Go to a store page on the selected build. The flag sticks for the rest of the test."""
    flag = "1" if STORE_MODE == "fixed" else "0"

    def _open(path: str = "index.html"):
        page.goto(f"{APP_URL}/{path}?fixed={flag}")
        return page

    return _open


def money(text: str) -> float:
    """'-$12.40' -> -12.4"""
    return float(text.strip().replace("$", ""))


def add_product_to_basket(page, product_id: str):
    page.get_by_test_id(f"product-card-{product_id}").click()
    page.get_by_test_id("add-to-cart").click()
    page.get_by_test_id("nav-cart").click()
