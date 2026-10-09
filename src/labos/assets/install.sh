#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
role="${1:-$(cat ROLE)}"
case "$role" in agent|central) ;; *) echo 'ROLE must be agent or central' >&2; exit 1 ;; esac
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
python3 -m venv .venv
if [[ -n "${LABOS_WHEELHOUSE:-}" ]]; then
  .venv/bin/python -m pip install --no-index --find-links "$LABOS_WHEELHOUSE" -r "requirements-$role.txt"
else
  .venv/bin/python -m pip install -r "requirements-$role.txt"
fi
PYTHONPATH="$PWD/src" .venv/bin/python -m labos --help
