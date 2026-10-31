"""Generated tests get no secrets, and the sandbox entry point works as a standalone script."""
import json
import subprocess
import sys
from pathlib import Path

from backend.runner import PLUGIN, run_test
from backend.testgen import assemble

ROOT = Path(__file__).resolve().parents[2]


def test_generated_test_cannot_see_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-should-not-leak")
    code = assemble('def test_x(page):\n    assert "FIREWORKS_API_KEY" not in os.environ\n'
                    '    assert not any("API_KEY" in k for k in os.environ)\n')
    assert run_test(code, tmp_path, "http://localhost:5173", fixed=False)["outcome"] == "pass"


def test_sandbox_entry_point_serves_the_store_and_reports(tmp_path):
    code = assemble('def test_x(page):\n    page.goto(url("index.html"))\n'
                    '    expect(page.get_by_test_id("build-mode")).to_have_text("build: fixed")\n')
    job = {"code": code, "plugin": PLUGIN, "workdir": str(tmp_path), "fixed": True, "store_dir": str(ROOT / "store"),
           "store_port": 5191, "action_timeout_ms": 10000, "timeout_s": 60}
    out = subprocess.run([sys.executable, str(ROOT / "backend" / "sandbox_exec.py")], input=json.dumps(job),
                         capture_output=True, text=True, timeout=90).stdout
    line = next(ln for ln in out.splitlines() if ln.startswith("@@RESULT@@"))
    result = json.loads(line.removeprefix("@@RESULT@@"))
    assert result["outcome"] == "pass", result["message"]
    assert result["screenshot_png"]  # the screenshot travels back as base64
