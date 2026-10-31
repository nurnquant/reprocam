"""Check what each configured provider accepts before any sweep spends money.

For every provider with a key in .env:
  - each reasoning_effort level: accepted or rejected, and reasoning tokens used
    (if the counts don't move across levels, the provider may be ignoring the setting)
  - image input: does a base64 PNG in a user message work, and is it actually seen

Run from the reprocam folder:  python scripts/preflight.py [--provider baseten] [--yes]
Writes data/preflight.json.
"""
import argparse
import base64
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.llm import PROVIDERS, get_client  # noqa: E402

EFFORTS = ["none", "minimal", "low", "medium", "high"]
# Needs a little thinking, so reasoning tokens should grow with effort.
QUESTION = ("A farmer has 17 sheep. All but 9 run away. He then buys 3 times as many as he "
            "has left. How many sheep does he have? Answer with just the number.")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "preflight.json")


def solid_png(rgb: tuple[int, int, int], size: int = 64) -> str:
    """Base64 data URL of a solid-colour PNG, built with the standard library."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + bytes(rgb) * size) * size)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def short_error(e: Exception) -> str:
    return f"{e.__class__.__name__}: {str(e)[:90]}".replace("\n", " ")


def reasoning_tokens(usage) -> int | None:
    details = getattr(usage, "completion_tokens_details", None)
    return getattr(details, "reasoning_tokens", None) if details else None


def check_effort(client, model: str, effort: str) -> dict:
    t = time.time()
    try:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": QUESTION}],
            reasoning_effort=effort, max_tokens=4000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": short_error(e)}
    return {"ok": True, "answer": (r.choices[0].message.content or "").strip()[:20],
            "reasoning_tokens": reasoning_tokens(r.usage),
            "completion_tokens": r.usage.completion_tokens if r.usage else None,
            "seconds": round(time.time() - t, 1)}


def check_image(client, model: str) -> dict:
    try:
        r = client.chat.completions.create(
            model=model, max_tokens=2000, reasoning_effort="low",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "This image is one solid colour. Name the colour in one word."},
                {"type": "image_url", "image_url": {"url": solid_png((220, 30, 30))}},
            ]}])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": short_error(e)}
    answer = (r.choices[0].message.content or "").strip()
    return {"ok": True, "answer": answer[:30], "saw_red": "red" in answer.lower()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=list(PROVIDERS), help="only check this one")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    names = [args.provider] if args.provider else list(PROVIDERS)
    configured = [n for n in names if os.getenv(PROVIDERS[n][1])]
    for n in names:
        if n not in configured:
            print(f"  [SKIP] {n:<10} {PROVIDERS[n][1]} not set")
    if not configured:
        sys.exit("No provider keys set in .env; nothing to check.")

    calls = len(configured) * (len(EFFORTS) + 1)
    print(f"\nPlan: {calls} small calls ({len(EFFORTS)} effort levels + 1 image) on {', '.join(configured)}.")
    print("Projected cost: well under $0.10 (short prompts; 'high' effort may use a few thousand tokens).")
    if not args.yes and input("Run? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    report = {}
    for name in configured:
        client, model = get_client(name)
        print(f"\n{name}  ({model})")
        efforts = {}
        for effort in EFFORTS:
            res = efforts[effort] = check_effort(client, model, effort)
            if res["ok"]:
                print(f"  effort {effort:<8} OK    reasoning_tokens={res['reasoning_tokens']!s:<6} "
                      f"answer={res['answer']!r} ({res['seconds']}s)")
            else:
                print(f"  effort {effort:<8} FAIL  {res['error']}")
        counts = {e: r["reasoning_tokens"] for e, r in efforts.items()
                  if r["ok"] and r["reasoning_tokens"] is not None}
        if len(counts) >= 2 and len(set(counts.values())) == 1:
            print("  WARNING: reasoning tokens identical at every level; effort may be ignored here")
        elif not counts:
            print("  NOTE: provider reports no reasoning_tokens; can't tell whether effort is applied")
        image = check_image(client, model)
        if image["ok"]:
            print(f"  image input     OK    answer={image['answer']!r}"
                  + ("" if image["saw_red"] else "  (did NOT say red: image may be dropped)"))
        else:
            print(f"  image input     FAIL  {image['error']}")
        report[name] = {"model": model, "efforts": efforts, "image": image}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
