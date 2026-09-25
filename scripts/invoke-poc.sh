#!/usr/bin/env bash
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [[ -n "${PYTHON:-}" ]]; then
    python="$PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
    python="$root/.venv/bin/python"
elif [[ -f "$root/.venv/Scripts/python.exe" ]]; then
    python="$root/.venv/Scripts/python.exe"
else
    python=python3
fi
exec "$python" -m src.operations.cli "$@"
