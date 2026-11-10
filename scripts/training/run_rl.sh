#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:$ROOT/verl${PYTHONPATH:+:$PYTHONPATH}"
exec python examples/training/rl.py "$@"
