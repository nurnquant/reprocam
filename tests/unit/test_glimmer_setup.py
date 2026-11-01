"""M9 Glimmer setup: one set of binary instructions everywhere, settings = docs/glimmer.md, scoring helpers."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import judge_metrics as jm  # noqa: E402


def test_upload_files_use_the_binary_instructions_and_rebuild_byte_for_byte(tmp_path, monkeypatch):
    for f in (jm.UPLOAD_TRAIN, jm.UPLOAD_EVAL):
        rows = [json.loads(line) for line in f.read_text().splitlines()]
        assert {r["messages"][0]["content"] for r in rows} == {jm.BINARY_SYSTEM}
        assert {jm.parse_verdict(r["messages"][-1]["content"]) for r in rows} == set(jm.VERDICTS)
    monkeypatch.setattr(jm, "UPLOAD_TRAIN", tmp_path / "train.jsonl")
    monkeypatch.setattr(jm, "UPLOAD_EVAL", tmp_path / "eval.jsonl")
    jm.write_upload_files()
    assert (tmp_path / "train.jsonl").read_bytes() == (ROOT / "data" / "glimmer_upload_train.jsonl").read_bytes()
    assert (tmp_path / "eval.jsonl").read_bytes() == (ROOT / "data" / "glimmer_upload_eval.jsonl").read_bytes()


def test_eval_rows_line_up_with_their_metadata():
    meta, chats = jm.load_eval()
    assert len(meta) == len(chats) == 40
    assert all(c["messages"][0]["content"] == jm.BINARY_SYSTEM for c in chats)


def test_settings_are_the_ones_recorded_before_the_run():
    from train_glimmer import SETTINGS
    doc = (ROOT / "docs" / "glimmer.md").read_text()
    assert "decided before the run" in doc
    assert (SETTINGS["base_model"], SETTINGS["renderer"]) == ("accounts/fireworks/models/muse-glimmer-30b", "muse_glimmer")
    assert (SETTINGS["lora_rank"], SETTINGS["lora_alpha"], SETTINGS["epochs"], SETTINGS["batch_size"]) == (8, 32, 3, 32)
    assert SETTINGS["learning_rate"] == 1e-4 and SETTINGS["in_run_sampling"] is False
    assert SETTINGS["train_attn"] and SETTINGS["train_mlp"] and SETTINGS["train_unembed"]
    for text in ("LoRA rank 8, alpha 32, on attention + MLP + unembedding", "3 / 32", "1e-4", "`muse_glimmer`",
                 "end-of-training checkpoint", "515 rows", "c9425896-2b42-4799-a4d4-46e6b475283d"):
        assert text in doc, text


def test_train_rows_check_passes_without_the_training_sdk():
    from train_glimmer import _check_train_rows
    assert len(_check_train_rows()) == 515  # imports of fireworks / the cookbook are lazy


def test_parse_verdict():
    assert jm.parse_verdict('{"verdict": "REPRODUCED"}') == "REPRODUCED"
    assert jm.parse_verdict('Thinking... {"verdict": "NOT_REPRODUCED"}') == "NOT_REPRODUCED"
    assert jm.parse_verdict('{"verdict": "TEST_ERROR"}') == "INVALID"  # not a binary answer
    assert jm.parse_verdict("") == jm.parse_verdict("no json") == "INVALID"


def test_end_to_end_counts_rule_rows_of_held_out_groups_only():
    ev = [{"group": "g1", "label": "REPRODUCED", "variant": "correct", "oracle": {"buggy": "assert_fail"}},
          {"group": "g2", "label": "NOT_REPRODUCED", "variant": "wrong_assertion", "oracle": {"buggy": "assert_fail"}}]
    all_rows = ev + [{"group": "g1", "label": "TEST_ERROR", "oracle": {"buggy": "error"}},
                     {"group": "g2", "label": "NOT_REPRODUCED", "oracle": {"buggy": "pass"}},
                     {"group": "other", "label": "TEST_ERROR", "oracle": {"buggy": "error"}}]
    e = jm.end_to_end(ev, ["REPRODUCED", "REPRODUCED"], all_rows)
    assert (e["n"], e["rule_rows"], e["model_rows"], e["accuracy"]) == (4, 2, 2, 0.75)
