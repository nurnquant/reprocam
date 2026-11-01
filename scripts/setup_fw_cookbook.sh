#!/usr/bin/env bash
# M9: the fw-ai cookbook's training package, for scripts/train_glimmer.py, in its own environment OUTSIDE
# this repo (default ../fw-cookbook). Run from the reprocam folder:  bash scripts/setup_fw_cookbook.sh
#
# torch substitution: the cookbook pins torch>=2.13, which has no wheel for Intel Macs (macOS x86_64).
# On those this installs torch 2.2.2 (the last Intel-Mac wheel) and the cookbook with --no-deps, then its
# other dependencies. The renderer only uses torch to build per-token weight tensors; nothing runs a model
# locally. On other platforms the cookbook's own pins are used.
set -euo pipefail

DEST="${1:-$(cd "$(dirname "$0")/../.." && pwd)/fw-cookbook}"
COMMIT=57968a2237b663be33078d2747a28463983ae134  # fw-ai/cookbook main, Oct 21 2026 (the version tested)

mkdir -p "$DEST"
if [ ! -d "$DEST/cookbook/.git" ]; then
  git clone -q https://github.com/fw-ai/cookbook "$DEST/cookbook"
fi
git -C "$DEST/cookbook" fetch -q --depth 1 origin "$COMMIT"
git -C "$DEST/cookbook" checkout -q "$COMMIT"

TRAINING="$DEST/cookbook/training"
PY="$TRAINING/.venv/bin/python"
[ -x "$PY" ] || uv venv -q -p 3.11 "$TRAINING/.venv"

cd "$DEST"  # not inside the cookbook: uv would apply its pyproject constraints (torch>=2.13) to every install
if [ "$(uname -s)-$(uname -m)" = "Darwin-x86_64" ]; then
  uv pip install -q --python "$PY" "torch==2.2.2" "numpy<2"
  uv pip install -q --python "$PY" --no-deps -e "$TRAINING"
  uv pip install -q --python "$PY" "fireworks-ai>=1.2.30,<2" "pydantic>=2.9.2,<2.13" tqdm tiktoken \
    "transformers==5.10.4" "huggingface-hub>=1.5.0,<2.0" python-dotenv "httpx[http2]>=0.23.0,<1" aiohttp \
    packaging certifi pillow orjson protobuf pyqwest
else
  uv pip install -q --python "$PY" -e "$TRAINING"
  uv pip install -q --python "$PY" protobuf pyqwest
fi

"$PY" -c "
import importlib.metadata as m, torch
from training.renderer import get_renderer
from fireworks.training.sdk import FiretitanServiceClient
print('fw-cookbook ready:', m.version('fireworks-ai'), 'torch', torch.__version__)"
echo "python for train_glimmer.py: $PY"
