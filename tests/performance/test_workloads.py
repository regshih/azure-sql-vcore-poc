import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.experiments.common import ARTIFACTS
from src.experiments.matrix import plan
from src.experiments.outcomes import OUTCOMES, classify, percentile, summarize
from src.experiments.profiles import Profile, load_profile
from src.experiments.runner import run
from src.experiments.workload import Schedule, Workload


def test_all_profiles_valid_and_no_unsafe_import_side_effects():
    profiles = Path(__file__).parents[2] / "load-tests" / "profiles"
    assert len(list(profiles.glob("*.yaml"))) == 13
    for path in profiles.glob("*.yaml"):
        assert load_profile(str(path)).profile_hash


@pytest.mark.parametrize("name,equivalent", [("expected", 86400), ("business-hours", 28800)])
def test_daily_volume_arithmetic(name, equivalent):
    profile = load_profile(name)
    model = profile.volume_model()
    assert model["scheduled_read_requests"] == pytest.approx(50000)
    assert model["modeled_daily_read_requests"] == pytest.approx(50000)
    assert model["acceleration_factor"] == equivalent / profile.duration
    assert profile.scheduled_requests > 50000
    assert isinstance(model["sql_read_queries"], str)


@pytest.mark.parametrize("minutes", [1, 5, 15])
def test_spike_plateau_duration(minutes):
    profile = load_profile(f"spike-{minutes}-minute")
    phase = max(profile.phases, key=lambda item: item.multiplier)
    assert phase.fraction * profile.duration == minutes * 60


def test_matrix_fifteen_cases_and_identical_cross_tier_profiles():
    cases = {item["test"]: item for item in plan()}
    assert len(cases) == 15
    assert cases[3]["profile_hash"] == cases[5]["profile_hash"] == cases[7]["profile_hash"]
    assert cases[4]["profile_hash"] == cases[6]["profile_hash"] == cases[11]["profile_hash"]
    assert cases[1]["profile_hash"] == cases[9]["profile_hash"]
    assert cases[12]["auto_pause"] and cases[13]["idle_after"]
    assert cases[14]["failover"] and cases[15]["geo"]


def test_config_overrides_and_unsafe_upper_bounds():
    profile = load_profile("smoke", users=3, duration=7, rate=11, write_ratio=0.1)
    assert (profile.users, profile.duration, profile.rate, profile.write_ratio) == (3, 7, 11, 0.1)
    for overrides in ({"users": 21}, {"rate": 21}, {"duration": 901}, {"write_ratio": 0.1}):
        with pytest.raises(ValidationError):
            load_profile("connection-storm", **overrides)
    with pytest.raises(ValidationError):
        Profile(name="bad", phases=[{"fraction": 0.1, "multiplier": 1}])


def test_deterministic_hot_skew_and_cursor_following():
    profile = load_profile("expected", product_count=1000, write_ratio=0)
    left, right = Workload(profile, 2), Workload(profile, 2)
    assert [left.identifier() for _ in range(50)] == [right.identifier() for _ in range(50)]
    hot_count = sum(left.identifier() <= 100 for _ in range(10000))
    assert 7900 < hot_count < 8500
    left.accept_page("paginated-lookup", {"next_cursor": "page-two"})
    for _ in range(100):
        request = left.next_request()
        if request.operation == "paginated-lookup":
            assert request.params["cursor"] == "page-two"
            break
    else:
        pytest.fail("Deterministic workload never reached pagination")
    left.accept_page("paginated-lookup", {"next_cursor": None})
    assert "paginated-lookup" not in left.cursors


def test_scheduler_does_not_catch_up_missed_arrivals():
    scheduler = Schedule(load_profile("smoke", rate=10))
    assert scheduler.acquire(0) == (True, 0)
    assert scheduler.acquire(0.01)[0] is False
    assert scheduler.acquire(1)[0] is True
    assert scheduler.missed == 9
    assert scheduler.issued == 2


def test_outcomes_do_not_invent_retry_or_deadlock_data():
    assert classify(500, None, None) == OUTCOMES[-1]
    assert classify(504, None, None) == "Unknown and requiring investigation"
    assert classify(504, "database_command_timeout", 0) == "Database command timeout"
    assert classify(None, None, None, True) == "Client-side timeout"
    assert classify(503, "deadlock_victim", 1) == "Deadlock victim"
    assert classify(200, None, 1) == "Unknown and requiring investigation"
    assert classify(200, "completed_after_retry", 1) == "Completed after retry"
    summary = summarize([{"outcome": OUTCOMES[0], "elapsed_ms": 10}], 1)
    assert summary["retried_request_count"] is None
    assert summary["database_calls"] is None
    assert summary["p95_ms"] == 10
    assert percentile([0, 10, 20, 30], 50) == 15
    assert percentile([0, 10, 20, 30], 95) == pytest.approx(28.5)
    assert percentile([], 99) is None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/products?") or self.path.startswith("/api/activity"):
            self.respond({"items": [], "next_cursor": None})
        else:
            self.respond({"id": 1})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.respond({"items": [], "missing_ids": []})

    def respond(self, body):
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-POC-Outcome", "completed_normally")
        self.send_header("X-Retry-Count", "0")
        self.send_header("X-DB-Calls", "1")
        self.send_header("X-Cache-Hit", "false")
        self.end_headers()
        self.wfile.write(payload)


def test_real_headless_locust_produces_complete_local_evidence(workdir, monkeypatch, capsys):
    monkeypatch.delenv("POC_INTERNAL_API_TOKEN", raising=False)
    archived = []

    def archive(directory, config_path):
        archived.append(json.loads((directory / "manifest.json").read_text()))
        assert all((directory / artifact).is_file() for artifact in ARTIFACTS)

    monkeypatch.setattr("src.experiments.storage.archive_if_configured", archive)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        directory = run(
            load_profile("smoke", duration=4, rate=10, write_ratio=0),
            f"http://127.0.0.1:{server.server_port}",
            output=workdir / "run",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert all((directory / artifact).is_file() for artifact in ARTIFACTS)
    summary = json.loads((directory / "workload-summary.json").read_text())
    assert summary["request_count"] >= 1
    assert summary["failed_request_count"] == 0
    assert summary["p95_ms"] > 0
    assert (directory / "locust_stats.csv").is_file()
    assert "POC_EVIDENCE " in capsys.readouterr().out
    request_log = (directory / "requests.jsonl").read_text()
    assert "Authorization" not in request_log
    assert "http://" not in request_log
    assert len(archived) == 1
    assert archived[0]["status"] == "completed"
    assert archived[0]["end_utc"] is not None
