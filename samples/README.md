# Sample bug videos

Real narrated recordings of the three demo bugs in the Lumen & Loom store (`python scripts/serve_store.py`).

| File | Bug id | What the tester does |
|---|---|---|
| `bug1.mov` | `neg_total` | Adds Linen Tea Towels, applies `GLOW20` twice, total goes negative |
| `bug2.mov` | `qty_stepper` | Adds an item, presses "−" at quantity 1, still charged |
| `bug3.mov` | `zip_hang` | Checks out with ZIP `02139`, "Place order" spins forever |

Every recording starts from a clean buggy session: open
`http://localhost:5173/index.html?fixed=0&reset=1` (empty basket, no promos; `reset` removes itself
from the address bar, so it never shows in the video).

Recorded with QuickTime (File → New Screen Recording, microphone on), narrating in plain words
what is being done and what went wrong. 30–90 s each, under 25 MB.
