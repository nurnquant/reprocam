"""Chart for M4b: data/effort_sweep.jsonl -> docs/effort_sweep.png (needs matplotlib, a dev-only dependency).

Two panels on one effort axis, never a dual axis: how many runs reproduced and were verified
(of 9 per effort), and what each run cost (every run as a dot, the mean as a bar).
"""
import json
import random
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ROWS = ROOT / "data" / "effort_sweep.jsonl"
OUT = ROOT / "docs" / "effort_sweep.png"
EFFORTS = ["low", "medium", "high"]
BUGS = ["bug1", "bug2", "bug3"]
# reference palette (dataviz skill): one series -> slot 1; text and grid in text/recessive tokens
SERIES, SURFACE, INK, INK_2, GRID = "#2a78d6", "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"


def main():
    all_rows = [json.loads(line) for line in ROWS.read_text().splitlines()]
    rows = [r for r in all_rows if not r.get("superseded")]
    superseded = [r for r in all_rows if r.get("superseded")]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
                         "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2})
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4.4), facecolor=SURFACE, gridspec_kw={"wspace": 0.28})
    for ax in (a, b):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)

    labels = []
    for i, effort in enumerate(EFFORTS):
        runs = [r for r in rows if r["effort"] == effort]
        ok = sum(r["success"] for r in runs)
        per_bug = "\n".join(f"{bug} {sum(r['success'] for r in runs if r['bug'] == bug)}/"
                            f"{sum(1 for r in runs if r['bug'] == bug)}" for bug in BUGS)
        labels.append(f"{effort}\n{per_bug}")
        a.bar(i, ok, width=0.5, color=SERIES)
        a.text(i, ok + 0.15, f"{ok}/{len(runs)}", ha="center", va="bottom", color=INK, fontweight="bold")

        costs = [r["cost_usd"] for r in runs if r["verdict"] != "ERROR"]
        rnd = random.Random(i)
        b.scatter([i + rnd.uniform(-0.13, 0.13) for _ in costs], costs, s=34, color=SERIES, alpha=0.75,
                  edgecolors=SURFACE, linewidths=1.2, zorder=3)
        if costs:
            m = mean(costs)
            b.hlines(m, i - 0.24, i + 0.24, color=INK, linewidth=2, zorder=4)
            b.text(i + 0.27, m, f"${m:.3f}", va="center", color=INK, fontsize=9)

    a.set_ylim(0, 9.8)
    a.set_yticks(range(0, 10, 3))
    a.set_title("Reproduced and verified (of 9 runs)", loc="left", color=INK, fontsize=11)
    b.set_title("Model cost per run (USD): runs and mean", loc="left", color=INK, fontsize=11)
    b.set_ylim(bottom=0)
    a.set_xticks(range(len(EFFORTS)), labels, linespacing=1.5)
    b.set_xticks(range(len(EFFORTS)), EFFORTS)
    for ax in (a, b):
        ax.set_xlim(-0.6, len(EFFORTS) - 0.3)
    for tick in a.get_xticklabels():  # effort + per-bug counts in secondary ink; the bar value carries the headline
        tick.set_color(INK_2)

    hits = {e: sum(r.get("limit_hits") or 0 for r in rows if r["effort"] == e) for e in EFFORTS}
    note = (f"On our 3 bugs · Muse Spark Open on Fireworks · test writing + judge at each effort, understanding fixed "
            f"(cached steps) · 3 runs per bug and effort · known-good build check on\n"
            f"Output-limit hits in the runs shown: " + ", ".join(f"{e} {hits[e]}" for e in EFFORTS)
            + " · cells ran at a 16,000-token limit that no call came near (largest 7,948)")
    if superseded:
        note += (f";\nbefore that, {len(superseded)} high cell hit it (all 16,000 tokens spent on reasoning) and was re-run at 32,000 "
                 f"(largest output 11,723). Original row kept, marked superseded")
    fig.text(0.01, -0.13, note, color=INK_2, fontsize=8.5, va="top")
    fig.savefig(OUT, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    print(f"wrote {OUT.relative_to(ROOT)} from {len(rows)} runs")


if __name__ == "__main__":
    main()
