from unittest.mock import Mock

import pytest

from src.experiments import runner
from src.experiments.profiles import load_profile


def database(status="Online", delay=15, compute="Serverless"):
    return {
        "status": status,
        "computeModel": compute,
        "autoPauseDelay": delay,
        "sku": {"name": "GP_S_Gen5", "capacity": 4},
    }


def test_idle_disposes_pool_and_never_discards_failed_first_request(workdir, monkeypatch):
    show = Mock(side_effect=[database(), database("Paused"), database()])
    monkeypatch.setattr(runner, "sql_configuration", show)
    monkeypatch.setattr(runner, "command_json", lambda _: [])
    monkeypatch.setattr(runner, "invoke_locust", lambda *args: 0)
    maintenance = Mock(return_value={"pool_disposed": True, "readiness_mode": "process"})
    monkeypatch.setattr(runner.client, "maintenance", maintenance)
    first_request = Mock(return_value=Mock(status_code=500, headers={}))
    monkeypatch.setattr(runner.httpx, "get", first_request)
    result = runner.observe_idle(
        "http://localhost",
        load_profile("idle-resume"),
        workdir,
        dict.fromkeys(("subscription_id", "resource_group", "sql_server", "database"), "example"),
        timeout=1800,
        interval=30,
        slack=600,
        no_other_clients=True,
        run_id="run-local",
    )
    assert result["first_request"]["http_status"] == 500
    assert result["first_request"]["outcome"] == "Unknown and requiring investigation"
    first_request.assert_called_once()
    assert [call.args[1] for call in maintenance.call_args_list] == ["idle", "resume"]
    assert show.call_count == 3
    assert result["pause_observed_utc"] is not None
    assert result["resume_observed_utc"] is not None


@pytest.mark.parametrize("delay", [-1, 0])
def test_idle_rejects_disabled_autopause_before_workload(workdir, monkeypatch, delay):
    monkeypatch.setattr(runner, "sql_configuration", lambda _: database(delay=delay))
    workload = Mock()
    monkeypatch.setattr(runner, "invoke_locust", workload)
    with pytest.raises(ValueError, match="auto-pause enabled"):
        runner.observe_idle(
            "http://localhost",
            load_profile("idle-resume"),
            workdir,
            {},
            timeout=1800,
            interval=30,
            slack=600,
            no_other_clients=True,
            run_id="run-local",
        )
    workload.assert_not_called()


def test_idle_rejects_geo_replication(workdir, monkeypatch):
    monkeypatch.setattr(runner, "sql_configuration", lambda _: database())
    monkeypatch.setattr(runner, "command_json", lambda _: [{"replication": "enabled"}])
    with pytest.raises(ValueError, match="geo-replication"):
        runner.observe_idle(
            "http://localhost",
            load_profile("idle-resume"),
            workdir,
            dict.fromkeys(
                ("subscription_id", "resource_group", "sql_server", "database"), "example"
            ),
            timeout=1800,
            interval=30,
            slack=600,
            no_other_clients=True,
            run_id="run-local",
        )
