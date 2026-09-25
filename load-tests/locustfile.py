"""Headless runner entry: all settings arrive through a local profile JSON file."""

import json
import os
import time
from pathlib import Path

import gevent
from locust import HttpUser, events, task
from requests.exceptions import Timeout

from src.experiments.client import internal_headers
from src.experiments.common import numeric_header, utc_now, write_json
from src.experiments.outcomes import classify, native_outcome
from src.experiments.profiles import Profile
from src.experiments.workload import Schedule, Workload

profile = Profile.model_validate_json(Path(os.environ["POC_PROFILE_FILE"]).read_text())
output = Path(os.environ["POC_RUN_DIRECTORY"])
run_id = os.environ["POC_RUN_ID"]
schedule = Schedule(profile)
started = 0.0
user_count = 0
event_file = None


@events.test_start.add_listener
def start_test(environment, **kwargs):
    global started, event_file
    started = time.monotonic()
    event_file = (output / "requests.jsonl").open("w", encoding="utf-8")


@events.test_stop.add_listener
def stop_test(environment, **kwargs):
    if event_file:
        event_file.close()
    write_json(
        output / "schedule.json",
        {
            "missed_schedule_slots": schedule.missed,
            "issued_requests": schedule.issued,
            "measurement_seconds": time.monotonic() - started,
        },
    )


class BusinessUser(HttpUser):
    def on_start(self):
        global user_count
        self.index = user_count
        user_count += 1
        self.workload = Workload(profile, self.index)
        self.sequence = 0

    @task
    def business_operation(self):
        while True:
            acquired, delay = schedule.acquire(time.monotonic() - started)
            if acquired:
                break
            gevent.sleep(delay)
        self.sequence += 1
        request = self.workload.next_request()
        correlation = f"{run_id}-u{self.index}-n{self.sequence}"
        headers = {
            "X-Test-Run-Id": run_id,
            "X-Workload-Profile": profile.name,
            "X-Correlation-ID": correlation,
        }
        if request.write:
            headers["Idempotency-Key"] = correlation
        if profile.scenario in {"storm", "slow"}:
            headers["X-POC-Unsafe-Test"] = "true"
            headers.update(internal_headers())
        timestamp = utc_now()
        began = time.monotonic()
        with self.client.request(
            request.method,
            request.path,
            name=request.operation,
            params=request.params,
            json=request.body,
            headers=headers,
            timeout=profile.request_timeout,
            allow_redirects=False,
            catch_response=True,
        ) as response:
            elapsed = (time.monotonic() - began) * 1000
            retry_count = numeric_header(response.headers.get("X-Retry-Count"))
            outcome = classify(
                response.status_code or None,
                response.headers.get("X-POC-Outcome"),
                retry_count,
                isinstance(response.error, Timeout),
            )
            if not outcome.startswith("Completed"):
                response.failure(outcome)
            elif request.operation in {"paginated-lookup", "recent-activity"}:
                try:
                    self.workload.accept_page(request.operation, response.json())
                except ValueError:
                    response.failure("Invalid JSON response")
                    outcome = "Unknown and requiring investigation"
            cache_header = response.headers.get("X-Cache-Hit", "").lower()
            record = {
                "test_id": run_id,
                "correlation_id": correlation,
                "operation": request.operation,
                "write": request.write,
                "timestamp": timestamp,
                "http_status": response.status_code or None,
                "outcome": outcome,
                "native_outcome": native_outcome(response.headers.get("X-POC-Outcome")),
                "final_result": outcome,
                "elapsed_ms": elapsed,
                "retry_count": retry_count,
                "db_calls": numeric_header(response.headers.get("X-DB-Calls")),
                "cache_hit": (
                    cache_header == "true" if cache_header in {"true", "false"} else None
                ),
                "pool_wait_ms": numeric_header(response.headers.get("X-Pool-Wait-Ms")),
                "attempt_number": None,
                "error_code": None,
                "retry_decision": None,
                "retry_delay_ms": None,
                "database_target_role": None,
            }
            if event_file:
                event_file.write(json.dumps(record, allow_nan=False) + "\n")
                event_file.flush()
