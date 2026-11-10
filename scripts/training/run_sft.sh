#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:$ROOT/verl${PYTHONPATH:+:$PYTHONPATH}"
exec torchrun --standalone --nproc_per_node="${PLAYER1_NPROC_PER_NODE:-1}" examples/training/sft.py "$@"
