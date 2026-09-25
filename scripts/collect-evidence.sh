#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [[ -x "$root/.venv/bin/python" ]]; then python="$root/.venv/bin/python"
elif [[ -x "$root/.venv/Scripts/python.exe" ]]; then python="$root/.venv/Scripts/python.exe"
elif [[ -n "${PYTHON:-}" ]]; then python="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then python=python3
else python=python
fi
exec "$python" -m src.experiments.evidence "$@"
