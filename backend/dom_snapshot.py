"""Compact map of the app's elements, so the model picks real selectors instead of inventing them.

    python -m backend.dom_snapshot            # writes data/dom_map.json, prints size

Walks the pages in store/crawl.json in one browser session (so the basket is filled before the
cart and checkout are mapped) and records every element with a data-testid, plus interactive
elements without one. Row: {page, testid, within, role, name, text, hidden}.
`within` is the nearest ancestor testid, for scoped selectors like
page.get_by_test_id("cart-line-linen-towels").get_by_test_id("qty-minus").
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CRAWL = ROOT / "store" / "crawl.json"
OUT = ROOT / "data" / "dom_map.json"

EXTRACT_JS = """
() => {
  const clip = (s, n) => (s || "").replace(/\\s+/g, " ").trim().slice(0, n) || null;
  const roleOf = (el) => {
    if (el.getAttribute("role")) return el.getAttribute("role");
    const tag = el.tagName.toLowerCase();
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "button") return "button";
    if (tag === "input") return el.type === "checkbox" ? "checkbox" : "textbox";
    if (tag === "select") return "combobox";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "form") return "form";
    return null;
  };
  const nameOf = (el) => {
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
    if (el.labels && el.labels[0]) return clip(el.labels[0].innerText, 40);
    if (el.placeholder) return el.placeholder;
    return null;
  };
  const sel = "[data-testid], a[href], button, input, select, textarea";
  return [...document.querySelectorAll(sel)].map((el) => {
    const parent = el.parentElement && el.parentElement.closest("[data-testid]");
    const kids = el.querySelectorAll("[data-testid]").length;
    return {
      testid: el.dataset.testid || null,
      within: parent ? parent.dataset.testid : null,
      role: roleOf(el),
      name: nameOf(el),
      // containers with testid children: their own text is just the children's text
      text: kids > 2 ? null : clip(el.innerText || el.value, 60),
      hidden: !(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
    };
  });
}
"""


def snapshot(app_url: str, crawl_path: Path = CRAWL) -> list[dict]:
    walk = json.loads(crawl_path.read_text())["pages"]
    rows, seen = [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for i, step in enumerate(walk):
            path = step["path"]
            # ?fixed=0 explicitly on the first page: the flag persists in localStorage
            sep = "&" if "?" in path else "?"
            page.goto(f"{app_url}/{path}{sep + 'fixed=0' if i == 0 else ''}")
            for action in step.get("actions", []):
                target = page.get_by_test_id(action.get("click") or action.get("fill"))
                target.fill(action["value"]) if "fill" in action else target.click()
            name = path.split("?")[0].removesuffix(".html")
            for el in page.evaluate(EXTRACT_JS):
                key = (el["testid"], el["within"], el["role"], el["name"], el["text"])
                if key in seen:  # header/footer repeat on every page
                    seen[key]["page"] = "*"
                    continue
                if not el["testid"] and not el["name"] and not el["text"]:
                    continue
                row = {"page": name, **el}
                seen[key] = row
                rows.append(row)
        browser.close()
    return [{k: v for k, v in r.items() if v not in (None, False)} for r in rows]


def to_prompt(rows: list[dict]) -> str:
    """One line per element: page | testid | within | role | name | text | hidden."""
    lines = []
    for r in rows:
        parts = [r["page"], r.get("testid") or "-", f"in:{r['within']}" if r.get("within") else "",
                 r.get("role") or "", f'name="{r["name"]}"' if r.get("name") else "",
                 f'text="{r["text"]}"' if r.get("text") else "", "hidden" if r.get("hidden") else ""]
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


def testids(rows: list[dict]) -> list[str]:
    return sorted({r["testid"] for r in rows if r.get("testid")})


def load_or_build(app_url: str | None = None) -> list[dict]:
    if OUT.exists():
        return json.loads(OUT.read_text())
    return build(app_url)


def build(app_url: str | None = None) -> list[dict]:
    app_url = (app_url or os.getenv("APP_URL", "http://localhost:5173")).rstrip("/")
    rows = snapshot(app_url)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    from serve_store import store_running

    url = os.getenv("APP_URL", "http://localhost:5173")
    with store_running(url):
        rows = build(url)
    text = to_prompt(rows)
    print(text)
    print(f"\n{len(rows)} elements, {len(testids(rows))} testids, ~{len(text) // 4} tokens -> {OUT.relative_to(ROOT)}")
