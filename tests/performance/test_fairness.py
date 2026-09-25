import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.experiments import client, fairness, matrix, runner
from src.experiments.common import NOT_DEMONSTRATED, write_json
from src.experiments.evidence import counter_delta
from src.experiments.profiles import load_profile
from src.experiments.sanitize import sanitize_value


def state(digest="a", stock=100):
    return {
        "status": "measured",
        "database_validation": "metadata_query_succeeded",
        "dataset_version": "synthetic-v1-s42-p24-w100",
        "dataset_kind": "synthetic-v1",
        "dataset_state": {"stock_units": stock, "products": 24, "work_items": 100},
        "dataset_state_fingerprint": digest * 64,
        "dataset_fingerprint_scope": "aggregate_state_not_full_content",
        "metadata_observed_at": "2026-01-01T00:00:00Z",
        "instance_id": "process-one",
    }


def deployment(idle=False):
    return {
        "application": "synthetic-azure-sql-vcore-poc",
        "synthetic_data_only": True,
        "poc_mode": True,
        "poc_marker": "sql-vcore",
        "environment": "poc",
        "repository_backend": "sql",
        "sql_adapter_configured": True,
        "control_scope": "single_process",
        "instance_id": "process-one",
        "idle": idle,
        "cache_mode": "disabled",
    }


def reset_receipt():
    return {
        "status": "reset-verified",
        "after": state(),
        "parameters": fairness.seed_parameters(state()),
    }


def test_equal_profiles_and_aggregates_never_establish_write_comparison_fairness():
    baseline = {"before": state(), "test_run_id": "earlier", "reset_provenance": None}
    result = fairness.assessment(state(), state("b", stock=99), None, baseline, 0.05)
    assert result["aggregate_prestate_matches_reference"] is True
    assert result["aggregate_state_changed"] is True
    assert result["data_state_comparison_status"] == "non-equivalent-or-unverified"
    assert result["fair_comparison_claim_allowed"] is False
    assert result["full_content_equivalence"] is None
    assert result["paired_deterministic_reset_verified"] is False


def test_both_runs_need_observed_matching_reset_provenance():
    receipt = reset_receipt()
    baseline = {"before": state(), "test_run_id": "earlier", "reset_provenance": receipt}
    result = fairness.assessment(state(), state("b"), receipt, baseline, 0.05)
    assert result["paired_deterministic_reset_verified"] is True
    assert result["data_state_comparison_status"] == "matched-reset-aggregate-state"
    assert result["fair_comparison_claim_allowed"] is False
    changed = deepcopy(receipt)
    changed["parameters"]["seed"] = 7
    assert not fairness.assessment(state(), state(), changed, baseline, 0.05)[
        "paired_deterministic_reset_verified"
    ]
    assert not fairness.assessment(state("c"), state(), receipt, baseline, 0.05)[
        "reset_before_run_verified"
    ]


def test_missing_fingerprints_stay_unknown_and_sanitization_keeps_refusal():
    result = fairness.assessment({}, {}, None, None, 0.05)
    assert result["aggregate_state_changed"] is None
    public = sanitize_value({"dataset_fairness": result})
    assert public["dataset_fairness"]["fair_comparison_claim_allowed"] is False
    assert (
        public["dataset_fairness"]["data_state_comparison_status"] == "non-equivalent-or-unverified"
    )
    assert sanitize_value(state())["dataset_state_fingerprint"] == "a" * 64


def test_snapshot_is_opt_in_and_uses_explicit_database_refresh(monkeypatch):
    get = Mock()
    monkeypatch.setattr(fairness.httpx, "get", get)
    assert fairness.snapshot("http://localhost", enabled=False)["status"] == NOT_DEMONSTRATED
    get.assert_not_called()
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", "test-only")
    get.return_value.json.return_value = {
        **state(),
        "database_validation": "metadata_query_succeeded",
    }
    assert fairness.snapshot("http://localhost", enabled=True)["status"] == "measured"
    assert get.call_args.kwargs["params"] == {"refresh_database": "true"}


def test_seed_parameters_are_derived_not_defaulted():
    value = fairness.seed_parameters(state())
    assert (value["seed"], value["size"], value["rows"], value["products"]) == (
        42,
        "small",
        100,
        24,
    )
    for modified in (
        {"dataset_kind": "customer"},
        {"dataset_version": "synthetic-v1-s42-p999-w100"},
        {"dataset_version": "synthetic-v1-s42-p24-w0"},
        {"status": NOT_DEMONSTRATED},
    ):
        with pytest.raises(ValueError):
            fairness.seed_parameters({**state(), **modified})


@pytest.mark.parametrize(
    "missing", ["allow_destructive", "confirm_poc", "no_other_clients", "single_instance"]
)
def test_reset_cannot_run_without_every_explicit_approval(workdir, monkeypatch, missing):
    mutate = Mock()
    monkeypatch.setattr(fairness.subprocess, "run", mutate)
    flags = dict.fromkeys(
        ("allow_destructive", "confirm_poc", "no_other_clients", "single_instance"), True
    )
    flags[missing] = False
    with pytest.raises(ValueError, match="approval"):
        fairness.reset_dataset("http://localhost", {}, {}, workdir / "reset.json", **flags)
    mutate.assert_not_called()


@pytest.mark.parametrize("fail", [False, True])
def test_reset_is_drained_guarded_observed_and_restored(workdir, monkeypatch, fail):
    order = []
    monkeypatch.setattr(
        client,
        "metadata",
        Mock(side_effect=[deployment(), deployment(True), deployment(True), deployment()]),
    )
    monkeypatch.setattr(fairness, "snapshot", lambda *a, **k: state())
    monkeypatch.setattr(
        client, "maintenance", lambda host, action: order.append(action) or {"pool_disposed": True}
    )

    def seed(command, **kwargs):
        order.append("seed")
        assert order[:2] == ["idle", "seed"]
        assert (
            "--reset" in command
            and "--allow-destructive-tests" in command
            and "--confirm-poc" in command
        )
        assert command[command.index("--rows") + 1] == "100"
        assert kwargs["env"]["POC_MODE"] == "true"
        value = {
            **state(),
            "status": "reset_and_seeded",
            "destructive_reset": True,
            "products": 24,
            "work_items": 100,
        }
        return Mock(returncode=int(fail), stdout=json.dumps(value))

    monkeypatch.setattr(fairness.subprocess, "run", seed)
    args = (
        "http://localhost",
        {"sql_server": "example", "database": "example"},
        fairness.seed_parameters(state()),
        workdir / "reset.json",
    )
    flags = dict(
        allow_destructive=True, confirm_poc=True, no_other_clients=True, single_instance=True
    )
    if fail:
        with pytest.raises(RuntimeError, match="reset failed"):
            fairness.reset_dataset(*args, **flags)
    else:
        assert fairness.reset_dataset(*args, **flags)["status"] == "reset-verified"
    receipt = json.loads((workdir / "reset.json").read_text())
    assert order == ["idle", "seed", "resume"]
    assert receipt["admission_restored"] is True
    assert receipt["status"] == ("failed" if fail else "reset-verified")
    with pytest.raises(FileExistsError):
        fairness.reset_dataset(*args, **flags)


def test_counter_deltas_reject_different_processes():
    result = counter_delta(
        {"instance_id": "first", "counts": {"requests": 10}},
        {"instance_id": "second", "counts": {"requests": 100}},
    )
    assert result["counts"] is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"repository_backend": "memory", "sql_adapter_configured": False},
        {"repository_backend": "sql", "sql_adapter_configured": False},
        {},
    ],
)
def test_sql_comparisons_reject_memory_or_unverified_adapters(metadata):
    with pytest.raises(ValueError, match="verified SQL adapter"):
        client.require_sql_backend(metadata)
    client.require_sql_backend({"repository_backend": "sql", "sql_adapter_configured": True})


def test_matrix_rejects_memory_before_any_database_control_operation(workdir, monkeypatch):
    monkeypatch.setattr(
        client,
        "metadata",
        lambda *a: {
            **deployment(),
            "repository_backend": "memory",
            "sql_adapter_configured": False,
        },
    )
    monkeypatch.setattr(client, "guard_unsafe", lambda *a: None)
    change = Mock()
    monkeypatch.setattr(matrix, "switch", change)
    with pytest.raises(ValueError, match="verified SQL adapter"):
        matrix.execute(
            workdir / "unused.json",
            "http://localhost",
            workdir / "matrix",
            confirm_poc=True,
            allow_unsafe=True,
            original_tuning="baseline",
            allowed_hosts=[],
            minimum=0.5,
            maximum=4,
            auto_pause_delay=15,
        )
    change.assert_not_called()


def test_metadata_refresh_surrounds_but_never_pollutes_counter_window(workdir, monkeypatch):
    order = []
    monkeypatch.setattr(client, "metadata", lambda *a: deployment())

    def dataset(*args, **kwargs):
        order.append("refresh")
        return {
            **state(),
            "product_count": 24,
            "work_item_count": 100,
            "counts_source": "dataset_seed_ledger",
            "schema_version": "1",
            "tuning_mode": "both",
        }

    counter = 0

    def counters(*args):
        nonlocal counter
        counter += 1
        order.append("counter")
        return {"instance_id": "process-one", "counts": {"requests": counter}}

    def workload(profile, host, directory, run_id):
        order.append("workload")
        (directory / "requests.jsonl").write_text("")
        return 0

    monkeypatch.setattr(fairness, "snapshot", dataset)
    monkeypatch.setattr(client, "snapshot", counters)
    sampler = Mock(samples=[], summary=Mock(return_value={}))
    monkeypatch.setattr(runner, "MetricsSampler", lambda *a: sampler)
    monkeypatch.setattr(runner, "invoke_locust", workload)
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", lambda *a: None)
    profile = load_profile("smoke", product_count=24, duration=1)
    directory = runner.run(
        profile,
        "http://localhost",
        output=workdir / "observed",
        observe_dataset_state=True,
    )
    final = json.loads((directory / "manifest.final.json").read_text())
    assert order == ["refresh", "counter", "workload", "counter", "refresh"]
    assert final["application_counter_delta"]["counts"]["requests"] == 1
    assert final["dataset_size"] == {
        "product_count": 24,
        "work_item_count": 100,
        "counts_source": "dataset_seed_ledger",
    }
    assert final["schema_version"] == "1" and final["tuning_mode"] == "both"
    assert final["profile_hash"] == profile.profile_hash


def test_out_of_bounds_product_distribution_requires_explicit_override(workdir, monkeypatch):
    monkeypatch.setattr(
        client,
        "metadata",
        lambda *a: {
            **deployment(),
            "product_count": 24,
            "counts_source": "dataset_seed_ledger",
        },
    )
    monkeypatch.setattr(client, "snapshot", lambda *a: pytest.fail("Counters started"))
    workload = Mock()
    monkeypatch.setattr(runner, "invoke_locust", workload)
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", lambda *a: None)
    profile = load_profile("smoke", product_count=100, duration=1)
    with pytest.raises(ValueError, match="explicitly set --product-count"):
        runner.run(profile, "http://localhost", output=workdir / "invalid")
    workload.assert_not_called()
    final = json.loads((workdir / "invalid" / "manifest.final.json").read_text())
    assert final["profile_hash"] == profile.profile_hash
    assert final["status"] == "failed"


@pytest.mark.parametrize("profile_name", ["slow-query", "connection-storm"])
def test_department_only_diagnostics_do_not_require_product_id_bounds(
    workdir, monkeypatch, profile_name
):
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", "test-only")
    monkeypatch.setattr(
        client,
        "metadata",
        lambda *a, **k: {**deployment(), **state(), "product_count": 24},
    )
    monkeypatch.setattr(client, "snapshot", lambda *a: None)
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", lambda *a: None)

    def workload(profile, host, directory, run_id):
        (directory / "requests.jsonl").write_text("")
        return 0

    monkeypatch.setattr(runner, "invoke_locust", workload)
    directory = runner.run(
        load_profile(profile_name, duration=1, product_count=100),
        "http://localhost",
        output=workdir / "diagnostic",
        allow_unsafe=True,
        confirm_poc=True,
    )
    assert json.loads((directory / "manifest.final.json").read_text())["status"] == "completed"


def test_failed_resume_is_recorded_without_claiming_restoration(workdir, monkeypatch):
    monkeypatch.setattr(
        client,
        "metadata",
        Mock(side_effect=[deployment(), deployment(True), deployment(True)]),
    )
    monkeypatch.setattr(fairness, "snapshot", lambda *a, **k: state())
    monkeypatch.setattr(
        client,
        "maintenance",
        Mock(side_effect=[{"pool_disposed": True}, RuntimeError("resume unavailable")]),
    )
    monkeypatch.setattr(fairness.subprocess, "run", Mock(return_value=Mock(returncode=1)))
    with pytest.raises(RuntimeError, match="restoration failed"):
        fairness.reset_dataset(
            "http://localhost",
            {"sql_server": "example", "database": "example"},
            fairness.seed_parameters(state()),
            workdir / "failed-reset.json",
            allow_destructive=True,
            confirm_poc=True,
            no_other_clients=True,
            single_instance=True,
        )
    receipt = json.loads((workdir / "failed-reset.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["admission_restored"] is False
    assert receipt["restoration_failure"] == "RuntimeError"


def test_process_drift_aborts_reset_before_sql_mutation(workdir, monkeypatch):
    monkeypatch.setattr(client, "metadata", lambda *a: deployment())
    monkeypatch.setattr(
        fairness,
        "snapshot",
        lambda *a, **k: {**state(), "instance_id": "different-process"},
    )
    mutate = Mock()
    monkeypatch.setattr(fairness.subprocess, "run", mutate)
    with pytest.raises(ValueError, match="provenance changed"):
        fairness.reset_dataset(
            "http://localhost",
            {},
            fairness.seed_parameters(state()),
            workdir / "reset.json",
            allow_destructive=True,
            confirm_poc=True,
            no_other_clients=True,
            single_instance=True,
        )
    mutate.assert_not_called()


def test_resume_does_not_claim_success_for_a_different_instance(monkeypatch):
    monkeypatch.setattr(
        client,
        "metadata",
        Mock(side_effect=[deployment(True), {**deployment(), "instance_id": "unexpected"}]),
    )
    monkeypatch.setattr(client, "maintenance", Mock())
    with pytest.raises(RuntimeError, match="original instance"):
        fairness.resume_verified("http://localhost", "process-one")


@pytest.mark.parametrize("reset_enabled", [False, True])
def test_matrix_never_resets_by_default_and_resets_before_each_approved_case(
    workdir, monkeypatch, reset_enabled
):
    database = {
        "sku": {"tier": "GeneralPurpose", "capacity": 2, "name": "GP_Gen5"},
        "computeModel": "Provisioned",
    }
    monkeypatch.setattr(matrix.client, "metadata", lambda _: deployment())
    monkeypatch.setattr(matrix.client, "guard_unsafe", lambda *a: None)
    monkeypatch.setattr(matrix.client, "set_cache", lambda *a: None)
    monkeypatch.setattr(matrix, "sql_configuration", lambda _: database)
    monkeypatch.setattr(matrix, "switch", lambda *a: {})
    monkeypatch.setattr(matrix, "tune", lambda *a: None)
    monkeypatch.setattr(matrix, "restore_database", lambda *a: None)
    monkeypatch.setattr(matrix, "serverless_report", lambda *a: None)
    monkeypatch.setattr(fairness, "snapshot", lambda *a, **k: state())
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", lambda *a: None)
    reset = Mock(return_value=reset_receipt())
    monkeypatch.setattr(fairness, "reset_dataset", reset)
    calls = []

    def run(profile, host, **kwargs):
        calls.append(kwargs)
        directory = kwargs["output"]
        directory.mkdir()
        dataset = fairness.assessment(
            state(),
            state("b"),
            kwargs["reset_provenance"],
            kwargs["comparison_baseline"],
            profile.write_ratio,
        )
        fairness.write_once(
            directory / "manifest.final.json",
            {
                "test_run_id": f"unique-{len(calls)}",
                "dataset_fairness": dataset,
            },
        )
        return directory

    monkeypatch.setattr(matrix, "run", run)
    config = workdir / "config.json"
    write_json(config, {})
    output = workdir / "matrix"
    matrix.execute(
        config,
        "http://localhost",
        output,
        confirm_poc=True,
        allow_unsafe=True,
        original_tuning="baseline",
        allowed_hosts=[],
        minimum=0.5,
        maximum=4,
        auto_pause_delay=15,
        selected=[3, 5],
        overrides={"product_count": 24},
        no_other_clients=True,
        reset_dataset=reset_enabled,
        allow_destructive=reset_enabled,
        single_instance=reset_enabled,
    )
    assert reset.call_count == (2 if reset_enabled else 0)
    assert calls[0]["comparison_baseline"] is None
    assert calls[1]["comparison_baseline"]["test_run_id"] == "unique-1"
    results = json.loads((output / "matrix-results.json").read_text())
    measured = [item for item in results if item.get("dataset_fairness")]
    assert len(measured) == 2
    assert measured[-1]["dataset_fairness"]["paired_deterministic_reset_verified"] == reset_enabled
    assert all(not item["dataset_fairness"]["fair_comparison_claim_allowed"] for item in measured)


def test_runner_keeps_immutable_manifests_and_distinct_run_namespaces(workdir, monkeypatch):
    monkeypatch.setattr(client, "metadata", lambda _: {})
    monkeypatch.setattr(client, "snapshot", lambda _: None)
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", lambda *a: None)
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    observed = []

    def workload(profile, host, directory, run_id):
        observed.append(run_id)
        (directory / "requests.jsonl").write_text("")
        return 0

    monkeypatch.setattr(runner, "invoke_locust", workload)
    for index in range(2):
        directory = runner.run(
            load_profile("smoke", duration=1),
            "http://localhost",
            output=workdir / str(index),
        )
        initial = json.loads((directory / "manifest.initial.json").read_text())
        final = json.loads((directory / "manifest.final.json").read_text())
        assert initial["end_utc"] is None
        assert final["end_utc"] is not None
        assert final["dataset_fairness"]["fair_comparison_claim_allowed"] is False
        assert "application_counter_delta" in final
        immutable = (directory / "manifest.final.json").read_bytes()
        with pytest.raises(FileExistsError):
            fairness.write_once(directory / "manifest.final.json", {"overwritten": True})
        assert (directory / "manifest.final.json").read_bytes() == immutable
    assert observed[0] != observed[1]
