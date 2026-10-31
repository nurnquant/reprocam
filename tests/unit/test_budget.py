"""Budget limits and the upload endpoint's rejections (nothing here reaches a model)."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend import api, budget


def _video(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=320x240:d={seconds}:r=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "STATE", tmp_path / "budget.json")
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "2")
    monkeypatch.setenv("MAX_RUNS_PER_IP", "1")


def test_charge_enforces_per_ip_then_per_day():
    assert budget.charge("1.1.1.1") == {"left_today": 1, "left_for_you": 0}
    with pytest.raises(budget.BudgetError) as e:
        budget.charge("1.1.1.1")
    assert e.value.status == 429
    budget.charge("2.2.2.2")
    with pytest.raises(budget.BudgetError, match="Today's live runs"):
        budget.charge("3.3.3.3")


def test_check_video_rejects_long_and_non_video(tmp_path):
    assert budget.check_video(_video(tmp_path / "ok.mp4", 3)) == pytest.approx(3, abs=0.3)
    with pytest.raises(budget.BudgetError) as e:
        budget.check_video(_video(tmp_path / "long.mp4", 95))
    assert e.value.status == 413
    (tmp_path / "x.mp4").write_text("not a video")
    with pytest.raises(budget.BudgetError) as e:
        budget.check_video(tmp_path / "x.mp4")
    assert e.value.status == 400


def test_upload_endpoint_rejects_before_any_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_IP", "0")
    started = []
    monkeypatch.setattr(api, "run_pipeline", lambda *a, **k: started.append(a))
    client = TestClient(api.app)
    long_video = _video(tmp_path / "long.mp4", 95).read_bytes()
    r = client.post("/runs", files={"video": ("long.mp4", long_video, "video/mp4")})
    assert r.status_code == 413
    ok_video = _video(tmp_path / "ok.mp4", 3).read_bytes()
    r = client.post("/runs", files={"video": ("ok.mp4", ok_video, "video/mp4")})
    assert r.status_code == 429
    assert started == []
