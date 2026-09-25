#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -n "${PYTHON:-}" ]]; then
  python_executable="$PYTHON"
elif [[ -x ".venv/bin/python" ]]; then
  python_executable=".venv/bin/python"
elif [[ -f ".venv/Scripts/python.exe" ]]; then
  python_executable=".venv/Scripts/python.exe"
else
  python_executable="python3.12"
fi
exec "$python_executable" -m src.operations.validate "$@"
