"""Ground-truth tests for the practice store.

Each test asserts the CORRECT behaviour, so it fails on the buggy build and passes on the
fixed one. Pick the build with STORE_MODE=buggy|fixed (default buggy). APP_URL overrides
the store address; if it points at localhost and nothing is listening, the store is
started for the test session.
"""
import os
import socket
import sys
import threading
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from serve_store import make_server  # noqa: E402

APP_URL = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
STORE_MODE = os.getenv("STORE_MODE", "buggy")

expect.set_options(timeout=3000)


def _listening(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope="session", autouse=True)
def store_server():
    url = urlparse(APP_URL)
    if url.hostname not in ("localhost", "127.0.0.1") or _listening("127.0.0.1", url.port or 80):
        yield
        return
    server = make_server(url.port or 80)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield
    server.shutdown()


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
