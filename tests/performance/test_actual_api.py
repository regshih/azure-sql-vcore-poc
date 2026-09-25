import os
import secrets
import socket
import subprocess
import sys
import time

import httpx

from src.experiments import client
from src.experiments.common import ROOT, read_json
from src.experiments.profiles import load_profile
from src.experiments.runner import run
from src.experiments.sanitize import sanitize
from src.experiments.scan import scan_directory


def test_actual_api_metadata_cache_and_headless_workload(workdir, monkeypatch, capsys):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", token)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    host = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "REPOSITORY_BACKEND": "memory",
        "APP_ENVIRONMENT": "test",
        "INTERNAL_API_TOKEN": token,
        "CACHE_BACKEND": "memory",
    }
    for name in (
        "WEBSITE_INSTANCE_ID",
        "WEBSITE_SITE_NAME",
        "CONTAINER_APP_NAME",
        "CONTAINER_APP_REVISION",
        "KUBERNETES_SERVICE_HOST",
    ):
        env.pop(name, None)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "critical",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = False
        for _ in range(100):
            assert process.poll() is None, "Local API exited before readiness"
            try:
                ready = httpx.get(host + "/healthz", timeout=1).status_code == 200
            except httpx.TransportError:
                time.sleep(0.1)
                continue
            if ready:
                break
        assert ready
        deployment = client.metadata(host)
        assert deployment["application"] == "synthetic-azure-sql-vcore-poc"
        client.set_cache(host, "disabled")
        assert client.metadata(host)["cache_mode"] == "disabled"
        client.set_cache(host, "memory")
        assert client.metadata(host)["cache_mode"] == "memory"
        directory = run(
            load_profile("smoke", duration=4, rate=10, product_count=3, write_ratio=0),
            host,
            output=workdir / "run",
        )
        summary = read_json(directory / "workload-summary.json")
        assert summary["request_count"] >= 1
        assert summary["failed_request_count"] == 0
        assert summary["retry_coverage"] == 1
        metrics = read_json(directory / "application-metrics.json")
        assert metrics["sample_count"] > 0
        assert metrics["run_local_counts"] is None
        assert "Bearer" not in capsys.readouterr().out
        archive = sanitize(directory, workdir / "shareable", confirm_no_customer_data=True)
        assert archive.is_file()
        assert not scan_directory(workdir / "shareable")
    finally:
        process.terminate()
        process.wait(timeout=15)
