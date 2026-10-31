"""Markdown bug report for a REPRODUCED run -> runs/<name>/ticket.md.

Built only from artifacts already in the run directory: steps.json, the reproducing attempt's
test and verdict, the buggy and fixed-build results, and evidence.png when there is one.
"""
import json
from pathlib import Path

from backend.runner import failure_summary


def write_ticket(run_dir: Path, attempt_dir: Path, buggy: dict, good: dict | None, verdict: dict,
                 run_info: dict) -> Path:
    """good: the same test on the known-good build, or None when no known-good build was given."""
    steps = json.loads((run_dir / "steps.json").read_text())
    claim = steps["bug_claim"]
    code = (attempt_dir / "test_repro.py").read_text()
    seg = run_dir / "segment.json"
    method = json.loads(seg.read_text()).get("method") if seg.exists() else None

    lines = [
        f"# {claim['summary']}",
        "",
        f"**Status:** {run_info['label']}",
        (f"**Known-good build:** {run_info['known_good']}: " +
         ("test passes" if good["outcome"] == "pass" else "test also fails: " + failure_summary(good.get("message")))
         if good else "**Known-good build:** none given, so the test was not checked where the bug is fixed"),
        f"**App:** {steps['app_url']} · **Run:** `{run_info['run_id']}` · **Attempts:** {run_info['attempt']}",
        "",
        "## Steps to reproduce",
    ]
    for s in steps["steps"]:
        what = f"`{s['value']}`" if s["value"] else ""
        lines.append(f"{s['n']}. **{s['action']}** {s['target']} {what}".rstrip())
    lines += ["", "## Expected", claim["expected"], "", "## Actual", claim["actual"], ""]
    if (run_dir / "evidence.png").exists():
        lines += ["## Evidence", f"![{claim['element']}](evidence.png)",
                  f"*{claim['element']}, frame {claim['frame_ref']} of the recording. Box: {method}.*", ""]
    lines += [
        "## Failing test",
        f"Fails on the buggy build with `{buggy.get('exc_type')}`:",
        "```",
        failure_summary(buggy.get("message")).replace(" | ", "\n"),
        "```",
        f"Judge ({verdict['decided_by']}): {verdict['reason']}",
        "",
        "```python",
        code.rstrip(),
        "```",
        "",
        "Run it: `APP_URL=<app> REPRO_FIXED=0 pytest test_repro.py` (`REPRO_FIXED=1` on the practice store's fixed build).",
        "",
        f"*Filed by ReproCam · models: {', '.join(run_info['models'])}*",
    ]
    out = run_dir / "ticket.md"
    out.write_text("\n".join(lines) + "\n")
    return out
