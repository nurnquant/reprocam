"""The UI shows the models a run recorded, never assumed ones."""
import json
import re
from pathlib import Path

from backend.api import SAMPLES, recorded_models, summary
from backend.llm import model_label

WEB = Path(__file__).resolve().parents[2] / "web"
MODEL_WORDS = re.compile(r"Muse |SAM 3|Voice Transcribe")


def _run(tmp_path, understand="muse-spark-1.3", calls=()):
    events = [{"stage": "understand", "status": "start"},
              {"stage": "understand", "status": "ok", "model": understand, "provider": "meta"}]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (tmp_path / "segment.json").write_text(json.dumps({
        "frame": {"path": "f.jpg"}, "method": "SAM 3.1", "calls": list(calls),
        "tried": [{"concept": "price", "model": "sam-3.1", "on_bug_frame": 1}]}))
    return summary(tmp_path, "runs")


def test_live_run_badge_model_is_the_recorded_one(tmp_path):
    assert _run(tmp_path)["models"]["understand"] == "muse-spark-1.3"


def test_decider_comes_from_the_recorded_call(tmp_path):
    call = {"model": "meta-models/muse-spark-open-1026", "provider": "baseten", "effort": "low"}
    seg = _run(tmp_path, calls=[call])["segment"]
    assert seg["decider"] == call and seg["sam_model"] == "sam-3.1"


def test_single_box_has_no_decider(tmp_path):
    assert not _run(tmp_path)["segment"]["decider"]


def test_cached_samples_report_what_they_recorded():
    assert recorded_models(SAMPLES / "bug1")["understand"] == "accounts/fireworks/models/muse-spark-open"
    assert summary(SAMPLES / "bug1", "samples")["segment"]["decider"]["provider"] == "fireworks"
    assert not summary(SAMPLES / "bug2", "samples")["segment"]["decider"]


def test_model_label():
    assert model_label("meta-models/muse-spark-open-1026") == "Muse Spark Open"
    assert model_label("muse-spark-1.3") == "Muse Spark"


def test_no_hard_coded_model_names_in_the_ui():
    assert not MODEL_WORDS.search((WEB / "index.html").read_text().replace("Every model in the product", ""))
    table = re.compile(r"^\s*\[/")  # MODEL_NAMES: the one id -> label table
    for line in (WEB / "app.js").read_text().splitlines():
        if not table.match(line) and not line.strip().startswith("//"):
            assert not MODEL_WORDS.search(line), line
