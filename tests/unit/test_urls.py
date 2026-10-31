"""Build-flag URLs: the url() helper, the parsed check, lint, and the runtime guard."""
import pytest

from backend.runner import run_test
from backend.testgen import _url_helper, assemble, check_goto_url, lint

BUG2_URL = "http://localhost:5173/product.html?id=pebble-light?fixed=0"


def test_bug2_hand_built_url_is_rejected():
    problem = check_goto_url(BUG2_URL, "0")
    assert problem and "exactly one fixed=0" in problem  # the '?fixed=0' ended up inside id


@pytest.mark.parametrize("u, fixed, ok", [
    ("http://a/product.html?id=pebble-light&fixed=0", "0", True),
    ("http://a/index.html?fixed=1", "1", True),
    ("http://a/index.html?fixed=0", "1", False),                 # wrong build
    ("http://a/index.html?fixed=0&fixed=0", "0", False),         # two flags
    ("http://a/index.html", "0", False),                         # no flag
    ("http://a/p.html?id=x%3Ffixed%3D0&fixed=0", "0", False),    # '?' inside a value
])
def test_check_goto_url(u, fixed, ok):
    assert (check_goto_url(u, fixed) is None) == ok


def test_url_helper_merges_flag_and_encodes_params():
    url = _url_helper()
    assert url("product.html", id="pebble-light") == "http://app/product.html?id=pebble-light&fixed=0"
    assert url("/index.html") == "http://app/index.html?fixed=0"
    assert url("index.html?fixed=1") == "http://app/index.html?fixed=0"   # never two flags
    assert check_goto_url(url("product.html?id=pebble-light?fixed=0"), "0") is not None


def test_lint_requires_url_helper_and_a_clean_parsed_url():
    good = assemble('def test_x(page):\n    page.goto(url("product.html", id="pebble-light"))\n')
    assert lint(good) is None
    by_hand = assemble('def test_x(page):\n    page.goto(f"{APP_URL}/product.html?id=pebble-light?fixed={FIXED}")\n')
    assert "url(" in lint(by_hand)
    bug2 = assemble('def test_x(page):\n    page.goto(url("product.html?id=pebble-light?fixed=0"))\n')
    assert "'?'" in lint(bug2) or "fixed" in lint(bug2)
    redefined = assemble('FIXED = "1"\n\ndef test_x(page):\n    page.goto(url("index.html"))\n')
    assert "redefine" in lint(redefined)


def test_runtime_guard_stops_a_hand_built_goto(tmp_path):
    # lint would refuse this; the guard is the second line of defence inside the test process
    code = assemble(f'def test_x(page):\n    page.goto("{BUG2_URL}")\n')
    result = run_test(code, tmp_path, "http://localhost:5173", fixed=False)
    assert result["outcome"] == "error" and result["exc_type"].endswith("GotoGuardError")
