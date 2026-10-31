"""Which Muse Spark Open model ids does this Baseten key reach?

Run from the reprocam folder:  python scripts/check_baseten.py
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
c = OpenAI(base_url="https://inference.baseten.co/v1", api_key=os.environ["BASETEN_API_KEY"])

try:
    ids = [m.id for m in c.models.list().data]
    muse = [i for i in ids if "muse" in i.lower() or "meta" in i.lower()]
    print(f"models visible: {len(ids)} total; meta/muse: {muse or 'none'}")
except Exception as e:  # noqa: BLE001
    print("list failed:", str(e)[:160])

for m in ["meta-models/muse-spark-open-1026", "meta-models/muse-spark-open"]:
    try:
        r = c.chat.completions.create(model=m, messages=[{"role": "user", "content": "Say OK"}], max_tokens=200)
        print("OK  ", m, "->", (r.choices[0].message.content or "").strip()[:40])
    except Exception as e:  # noqa: BLE001
        print("FAIL", m, "->", str(e)[:160])
