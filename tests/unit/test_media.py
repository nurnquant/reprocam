"""backend.media against a small generated clip (ffmpeg test pattern + tone)."""
import json
import subprocess
import wave

import pytest
from PIL import Image

from backend.media import MAX_FRAMES, pick_timestamps, prepare


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """6 s, 1920x1080: 3 s red then 3 s blue (one hard cut), with a 440 Hz stereo tone."""
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=1920x1080:d=3:r=30",
         "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=3:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6:sample_rate=48000",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v];[2:a]pan=stereo|c0=c0|c1=c0[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True)
    return path


def test_prepare_writes_transcribe_ready_audio_and_capped_frames(clip, tmp_path):
    result = prepare(clip, tmp_path)

    with wave.open(str(tmp_path / "audio.wav")) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)

    frames = result["frames"]
    assert 2 <= len(frames) <= MAX_FRAMES
    assert [f["t"] for f in frames] == sorted(f["t"] for f in frames)
    assert any(abs(f["t"] - 3.0) < 0.1 for f in frames), "hard cut at 3 s not picked"
    for f in frames:
        with Image.open(tmp_path / f["path"]) as img:
            assert img.width == 1280

    manifest = json.loads((tmp_path / "frames.json").read_text())
    assert manifest["has_audio"] and len(manifest["frames"]) == len(frames)


def test_pick_timestamps_fills_static_stretches():
    ts = pick_timestamps(10.0, changes=[])
    assert ts[0] == 0.0 and ts[-1] == pytest.approx(9.9)
    assert max(b - a for a, b in zip(ts, ts[1:])) <= 1.0


def test_pick_timestamps_keeps_strongest_changes_under_cap():
    changes = [(i * 0.5, i / 100) for i in range(1, 100)]  # 99 changes, rising score
    ts = pick_timestamps(60.0, changes, max_frames=8)
    assert len(ts) == 8
    assert 49.5 in ts  # strongest change survives
