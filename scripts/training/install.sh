#!/usr/bin/env bash
# Install the reference Linux/Python 3.12/CUDA 12.8 runtime into the active environment.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
lock="$root/requirements/training-cu128-py312.lock"
python - <<'PY'
import platform, sys
if sys.version_info[:2] != (3, 12) or platform.system() != 'Linux' or platform.machine() != 'x86_64':
    raise SystemExit('Training requires Linux x86_64 and Python 3.12')
PY
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$CUDA_HOME/bin:$PATH"
test -x "$CUDA_HOME/bin/nvcc" || { echo 'Set CUDA_HOME to a CUDA 12.8 development toolkit' >&2; exit 1; }
export MAX_JOBS="${MAX_JOBS:-4}"
export FLASH_ATTN_CUDA_ARCHS="${FLASH_ATTN_CUDA_ARCHS:-80;90}"
python -m pip install --index-url https://pypi.org/simple uv==0.11.19
python_path="$(python -c 'import sys; print(sys.executable)')"
# Native extension metadata/builds need the pinned PyTorch and build tools first.
python -m uv pip install --python "$python_path" --constraint "$lock" \
  --default-index https://pypi.org/simple --index https://download.pytorch.org/whl/cu128 \
  --index-strategy unsafe-best-match setuptools wheel packaging ninja psutil einops torch
python -m uv pip sync --python "$python_path" --no-build-isolation \
  --default-index https://pypi.org/simple --index https://download.pytorch.org/whl/cu128 \
  --index https://flashinfer.ai/whl --index-strategy unsafe-best-match "$lock"
python -m uv pip check --python "$python_path"
python -m playwright install chromium
