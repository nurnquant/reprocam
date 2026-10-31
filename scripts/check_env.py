"""Smoke-test the environment: tools + one tiny call per configured provider.

Run from the reprocam folder:  python scripts/check_env.py
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.llm import PROVIDERS, get_client  # noqa: E402

ok = True


def line(status, name, detail=""):
    print(f"  [{status}] {name:<12} {detail}")


print("\nTools")
for tool in ("git", "node", "ffmpeg", "gh"):
    path = shutil.which(tool)
    line("OK " if path else "MISSING", tool, path or "install with brew")
    ok &= bool(path) or tool == "gh"

try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        b.close()
    line("OK ", "playwright", "chromium launches")
except Exception as e:  # noqa: BLE001
    line("FAIL", "playwright", f"{e.__class__.__name__}: run 'playwright install chromium'")
    ok = False

print("\nModel providers")
for name, (_, key_var, _) in PROVIDERS.items():
    if not os.getenv(key_var):
        line("SKIP", name, f"{key_var} not set")
        continue
    try:
        client, model = get_client(name)
        t = time.time()
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ReproCam ready"}],
            max_tokens=300,
        )
        text = (r.choices[0].message.content or "").strip().replace("\n", " ")[:60]
        line("OK ", name, f"{model} -> '{text}' ({time.time() - t:.1f}s)")
    except Exception as e:  # noqa: BLE001
        line("FAIL", name, f"{e.__class__.__name__}: {str(e)[:120]}")
        ok = False

print("\nAll good." if ok else "\nFix the FAIL/MISSING lines above, then re-run.")
sys.exit(0 if ok else 1)
