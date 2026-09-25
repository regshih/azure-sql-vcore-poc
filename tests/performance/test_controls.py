from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.experiments import client, comparisons, matrix, runner
from src.experiments.common import write_json
from src.experiments.profiles import load_profile


def test_missing_token_never_probes_an_incompatible_public_metadata_alias(monkeypatch):
    monkeypatch.delenv("POC_INTERNAL_API_TOKEN", raising=False)
    request = Mock()
    monkeypatch.setattr(client.httpx, "get", request)
    assert client.metadata("http://localhost") == {}
    with pytest.raises(ValueError, match="POC_INTERNAL_API_TOKEN"):
        client.metadata("http://localhost", refresh_database=True)
    request.assert_not_called()


def test_metadata_uses_one_authenticated_client_for_plain_and_explicit_refresh(monkeypatch):
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", "test-only")
    request = Mock(return_value=Mock(json=Mock(return_value={"instance_id": "synthetic"})))
    monkeypatch.setattr(client.httpx, "get", request)
    client.metadata("http://localhost")
    client.metadata("http://localhost", refresh_database=True)
    plain, refreshed = request.call_args_list
    assert plain.args == refreshed.args == ("http://localhost/internal/metadata",)
    assert plain.kwargs["params"] is None
    assert refreshed.kwargs["params"] == {"refresh_database": "true"}
    assert plain.kwargs["headers"] == refreshed.kwargs["headers"]
    assert plain.kwargs["follow_redirects"] is False


@pytest.mark.parametrize("backend", ["redis", "memory"])
def test_cache_comparison_defaults_to_the_existing_backend(backend):
    deployment = {"configuration": {"cache_backend": backend}}
    assert client.comparison_cache_modes(deployment, None) == ["disabled", backend]
    assert client.comparison_cache_modes(deployment, f"{backend},disabled") == [backend, "disabled"]


@pytest.mark.parametrize(
    "requested", ["disabled,memory", "memory,redis", "disabled", "redis,redis"]
)
def test_redis_comparison_rejects_backend_switches_or_missing_control(requested):
    with pytest.raises(ValueError, match="existing cache backend"):
        client.comparison_cache_modes({"configuration": {"cache_backend": "redis"}}, requested)


@pytest.mark.parametrize("backend", [None, "disabled", [], "unexpected"])
def test_unconfigured_cache_is_not_created_by_comparison(backend):
    with pytest.raises(ValueError, match="Configure"):
        client.comparison_cache_modes({"configuration": {"cache_backend": backend}}, None)


def test_cache_toggle_and_restore_use_current_versions_and_never_set_backend(monkeypatch):
    state = {
        "instance_id": "single-process",
        "version": 7,
        "cache_enabled": True,
        "cache_backend": "redis",
        "cache_ttl_seconds": 15,
    }
    bodies = []
    monkeypatch.setattr(
        client.httpx,
        "get",
        lambda *a, **k: Mock(
            json=Mock(return_value=deepcopy(state)),
        ),
    )

    def put(url, **kwargs):
        assert url == "http://localhost/internal/config"
        body = kwargs["json"]
        bodies.append(body)
        assert set(body) == {"cache_enabled", "expected_version", "confirm"}
        assert body["expected_version"] == state["version"]
        previous = deepcopy(state)
        state["version"] += 1
        state["cache_enabled"] = body["cache_enabled"]
        return Mock(json=Mock(return_value={"previous": previous, "current": deepcopy(state)}))

    monkeypatch.setattr(client.httpx, "put", put)
    client.set_cache("http://localhost", "disabled")
    client.set_cache("http://localhost", "redis")
    client.set_cache("http://localhost", "redis")
    assert [body["expected_version"] for body in bodies] == [7, 8, 9]
    assert [body["cache_enabled"] for body in bodies] == [False, True, True]


def test_invalid_cache_comparison_fails_before_the_first_toggle(monkeypatch):
    monkeypatch.setattr(
        client,
        "metadata",
        lambda *a: {
            "repository_backend": "sql",
            "sql_adapter_configured": True,
            "cache_mode": "redis",
            "configuration": {"cache_backend": "redis"},
        },
    )
    monkeypatch.setattr(client, "guard_unsafe", lambda *a: None)
    toggle = Mock()
    monkeypatch.setattr(client, "set_cache", toggle)
    with pytest.raises(ValueError, match="existing cache backend"):
        runner.main(
            [
                "--profile",
                "cache-comparison",
                "--host",
                "http://localhost",
                "--cache-modes",
                "disabled,memory",
            ]
        )
    toggle.assert_not_called()


@pytest.mark.parametrize("mode", ["baseline", "index", "query", "both"])
def test_tuning_restoration_prefers_observed_mode_and_checks_optional_assertion(mode):
    assert client.original_tuning_mode(mode, None) == mode
    assert client.original_tuning_mode(mode, mode) == mode
    assert client.original_tuning_mode(None, mode) == mode
    other = "baseline" if mode != "baseline" else "both"
    with pytest.raises(ValueError, match="conflicts"):
        client.original_tuning_mode(mode, other)


def test_unknown_tuning_requires_explicit_assertion():
    with pytest.raises(ValueError, match="--original-tuning"):
        client.original_tuning_mode(None, None)
    with pytest.raises(ValueError, match="unsupported"):
        client.original_tuning_mode("future-server-mode", "baseline")


@pytest.mark.parametrize(
    "observed",
    [
        {},
        {"instance_id": "original"},
        {"instance_id": "other", "database_validation": "metadata_query_succeeded"},
        {"instance_id": "original", "database_validation": "not_performed_by_metadata_endpoint"},
    ],
)
def test_sql_scenarios_require_fresh_successful_observation_on_original_instance(observed):
    deployment = {
        "repository_backend": "sql",
        "sql_adapter_configured": True,
        "instance_id": "original",
    }
    with pytest.raises(ValueError, match="Fresh SQL metadata"):
        client.require_sql_observation(deployment, observed)
    client.require_sql_observation(
        deployment,
        {"instance_id": "original", "database_validation": "metadata_query_succeeded"},
    )


@pytest.mark.parametrize("scenario", ["matrix", "slow"])
def test_original_tuning_mismatch_aborts_before_compute_or_tuning_mutations(
    workdir, monkeypatch, scenario
):
    metadata = {
        "repository_backend": "sql",
        "sql_adapter_configured": True,
        "instance_id": "original-instance",
        "cache_mode": "disabled",
        "tuning_mode": "both",
        "database_validation": "metadata_query_succeeded",
    }
    monkeypatch.setattr(client, "metadata", lambda *a, **k: metadata)
    monkeypatch.setattr(client, "guard_unsafe", lambda *a: None)
    monkeypatch.setattr(matrix.fairness, "snapshot", lambda *a, **k: metadata)
    monkeypatch.setattr(
        matrix,
        "sql_configuration",
        lambda *a: {"sku": {"tier": "GeneralPurpose", "name": "GP_Gen5", "capacity": 2}},
    )
    mutations = Mock()
    monkeypatch.setattr(matrix, "switch", mutations)
    monkeypatch.setattr(comparisons, "switch", mutations)
    monkeypatch.setattr(matrix, "tune", mutations)
    monkeypatch.setattr(comparisons, "tune", mutations)
    config = workdir / "config.json"
    write_json(config, {})
    with pytest.raises(ValueError, match="conflicts"):
        if scenario == "matrix":
            matrix.execute(
                config,
                "http://localhost",
                workdir / "matrix",
                confirm_poc=True,
                allow_unsafe=True,
                original_tuning="baseline",
                allowed_hosts=[],
                minimum=0.5,
                maximum=4,
                auto_pause_delay=15,
                selected=[1],
            )
        else:
            comparisons.slow_query_comparison(
                load_profile("slow-query"),
                "http://localhost",
                workdir / "slow",
                config,
                "baseline",
                {"allow_unsafe": True, "confirm_poc": True, "allowed_hosts": []},
            )
    mutations.assert_not_called()


def original_database():
    return {
        "sku": {"tier": "GeneralPurpose", "name": "GP_S_Gen5", "family": "Gen5", "capacity": 4},
        "computeModel": "Serverless",
        "minCapacity": 1.0,
        "autoPauseDelay": 60,
        "maxSizeBytes": 34359738368,
        "zoneRedundant": False,
        "readScale": "Disabled",
        "licenseType": "LicenseIncluded",
        "requestedBackupStorageRedundancy": "Local",
    }


def test_restoration_uses_original_four_vcore_serverless_settings_not_default_two(
    workdir, monkeypatch
):
    original = original_database()
    config = workdir / "config.json"
    write_json(config, {})
    switch = Mock()
    monkeypatch.setattr(matrix, "switch", switch)
    monkeypatch.setattr(matrix, "sql_configuration", lambda *a: deepcopy(original))
    matrix.restore_database(config, original)
    switch.assert_called_once_with(config, "Serverless", 4.0, 1.0, 60)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sku", {"tier": "GeneralPurpose", "name": "GP_S_Gen5", "family": "Other", "capacity": 4}),
        ("minCapacity", 0.5),
        ("autoPauseDelay", -1),
        ("maxSizeBytes", 1),
        ("zoneRedundant", True),
        ("readScale", "Enabled"),
        ("licenseType", "BasePrice"),
        ("requestedBackupStorageRedundancy", "Geo"),
    ],
)
def test_restoration_reports_any_supported_configuration_drift(workdir, monkeypatch, field, value):
    original = original_database()
    config = workdir / "config.json"
    write_json(config, {})
    changed = {**original, field: value}
    monkeypatch.setattr(matrix, "switch", Mock())
    monkeypatch.setattr(matrix, "sql_configuration", lambda *a: changed)
    with pytest.raises(RuntimeError, match="differs"):
        matrix.restore_database(config, original)


def test_unsupported_family_rejected_before_restoration_mutation(monkeypatch):
    original = original_database()
    original["sku"]["family"] = "Other"
    switch = Mock()
    monkeypatch.setattr(matrix, "switch", switch)
    with pytest.raises(ValueError, match="Gen5"):
        matrix.restore_database(None, original)
    switch.assert_not_called()
