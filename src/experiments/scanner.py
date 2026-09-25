"""Compatibility entrypoint for legacy runner jobs; use experiments.runner for new jobs."""

from src.experiments.common import safe_main
from src.experiments.runner import main

if __name__ == "__main__":
    raise SystemExit(safe_main(main))
