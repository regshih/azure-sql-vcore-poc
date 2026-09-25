from __future__ import annotations

import os
import threading
from typing import Any

import httpx

from src.experiments.client import snapshot
from src.experiments.common import utc_now


class MetricsSampler:
    """Samples only process counters; never run this during an idle/pause wait."""

    def __init__(self, host: str, interval: float = 1) -> None:
        self.host = host
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if os.environ.get("POC_INTERNAL_API_TOKEN"):
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                value = snapshot(self.host)
                self.samples.append({"timestamp": utc_now(), "snapshot": value})
            except (httpx.HTTPError, ValueError) as exc:
                self.samples.append(
                    {
                        "timestamp": utc_now(),
                        "snapshot": None,
                        "failure_category": type(exc).__name__,
                    }
                )
            if self._stop.wait(self.interval):
                break

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                raise RuntimeError("Metrics sampler did not stop; idle test cannot proceed")

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sample_count": len(self.samples),
            "sampling_interval_seconds": self.interval,
            "scope": "sampled process-wide gauges, not exact maxima or per-run attribution",
        }
        for key in (
            "pool_utilization",
            "pool_size",
            "pool_checked_out",
            "active_requests",
            "queue_depth",
        ):
            values = [
                sample["snapshot"][key]
                for sample in self.samples
                if sample.get("snapshot")
                and isinstance(
                    sample["snapshot"].get(key),
                    (int, float),
                )
            ]
            result["maximum_" + key] = max(values) if values else None
        return result
