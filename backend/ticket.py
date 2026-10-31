"""Markdown bug report for a REPRODUCED run -> runs/<name>/ticket.md.

Built only from artifacts already in the run directory: steps.json, the reproducing attempt's
test and verdict, the buggy and fixed-build results, and evidence.png when there is one.
"""
import json
from pathlib import Path

from backend.runner import failure_summary


def write_ticket(run_dir: Path, attempt_dir: Path, buggy: dict, fixed: dict, verdict: dict,
                 run_info: dict) -> Path:
    steps = json.loads((run_dir / "steps.json").read_text())
    claim = steps["bug_claim"]
    code = (attempt_dir / "test_repro.py").read_text()
    seg = run_dir / "segment.json"
    method = json.loads(seg.read_text()).get("method") if seg.exists() else None

    lines = [
        f"# {claim['summary']}",
        "",
        f"**Status:** reproduced by an automated test · **Fixed build:** "
        f"{'test passes' if fixed['outcome'] == 'pass' else 'test still fails: ' + failure_summary(fixed.get('message'))}",
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
        "Run it: `APP_URL=<app> REPRO_FIXED=0 pytest test_repro.py` (set `REPRO_FIXED=1` for the fixed build).",
        "",
        f"*Filed by ReproCam · models: {', '.join(run_info['models'])}*",
    ]
    out = run_dir / "ticket.md"
    out.write_text("\n".join(lines) + "\n")
    return out
