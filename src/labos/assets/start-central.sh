#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PYTHONPATH="$PWD/src"
exec .venv/bin/python -m labos central --config "${1:-config.yaml}"
