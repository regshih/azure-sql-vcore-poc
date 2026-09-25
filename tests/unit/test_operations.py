from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from src.operations import azure, cli
from src.operations.azure import (
    AzureCLI,
    DeploymentConfig,
    OperationError,
    change_compute,
    require_tags,
    validate_capability,
)


def configuration(**kwargs: Any) -> DeploymentConfig:
    return DeploymentConfig(
        **{
            "subscription_id": UUID(int=1),
            "resource_group": "rg-synthetic-unit-test",
            "environment_name": "synthetic-test",
            "region": "centralus",
            "sql_server": "synthetic-sql",
            "database": "synthetic",
        }
        | kwargs,
    )


def capabilities(status: str = "Available") -> dict[str, Any]:
    return {
        "supportedServerVersions": [
            {
                "name": "12.0",
                "supportedEditions": [
                    {
                        "name": "GeneralPurpose",
                        "supportedServiceLevelObjectives": [
                            {
                                "name": "GP_S_Gen5_4",
                                "status": status,
                                "supportedMinCapacities": [{"value": 0.5, "status": "Default"}],
                                "supportedAutoPauseDelay": {"minValue": 15, "maxValue": 10080},
                                "zoneRedundant": True,
                            }
                        ],
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "values",
    [
        {"deployment_profile": "evaluation"},
        {"deployment_profile": "evaluation", "allow_evaluation_public_access": True},
        {"evaluation_ip": ".".join(str(octet) for octet in (0, 0, 0, 0))},
        {"evaluation_ip": ".".join(str(octet) for octet in (192, 168, 1, 2))},
        {"evaluation_ip": ".".join(["8"] * 4) + "/32"},
        {"enable_dr": True},
        {"enable_dr": True, "secondary_location": "centralus"},
        {"enable_dr": True, "secondary_location": "westus3", "sql_auto_pause_delay": 15},
        {"sql_compute_tier": "Serverless", "sql_vcores": 2},
        {"enable_business_critical": True, "sql_compute_tier": "Serverless", "sql_vcores": 4},
        {"sql_vcores": 8},
        {"sql_auto_pause_delay": 0},
        {"enable_alerts": True},
        {"alert_thresholds": {"unknown": 5}},
        {"alert_thresholds": {"cpu": 101}},
        {"alert_thresholds": {"cpu": float("nan")}},
        {"alert_thresholds": {"minimumRequests": 0}},
        {"unexpected_secret": "should-not-be-accepted"},
    ],
)
def test_configuration_rejects_unsafe_or_inconsistent_values(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        configuration(**values)


def test_secure_default_has_no_public_exception() -> None:
    config = configuration()
    assert config.deployment_profile == "secure"
    assert config.evaluation_ip == ""
    assert not config.allow_evaluation_public_access
    assert config.sql_vcores == 2
    assert not config.enable_dr
    assert not config.enable_business_critical
    assert not config.enable_legacy_redis
    assert not config.enable_alerts


@pytest.mark.parametrize("name", ["abc", "a" + "b" * 19])
def test_environment_prefix_accepts_bicep_length_boundaries(name: str) -> None:
    assert configuration(environment_name=name).environment_name == name


@pytest.mark.parametrize("name", ["ab", "a" + "b" * 20])
def test_environment_prefix_rejects_out_of_bounds_lengths(name: str) -> None:
    with pytest.raises(ValidationError):
        configuration(environment_name=name)


@pytest.mark.parametrize("archive_verified", [True, False])
def test_smoke_command_requires_evidence_not_only_job_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, archive_verified: bool
) -> None:
    operator = Mock()
    monkeypatch.setattr(cli, "load_config", lambda _: configuration())
    monkeypatch.setattr(cli, "AzureCLI", lambda *_: operator)
    monkeypatch.setattr(cli, "output_directory", lambda *_: tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path.parent)
    verify = Mock(
        return_value={"status": "verified"},
        side_effect=None if archive_verified else OperationError("Archive verification failed"),
    )
    monkeypatch.setattr(cli, "launch_smoke", verify)
    assert cli.main(["smoke", "--config", "synthetic.local.json", "--confirm-poc"]) == (
        0 if archive_verified else 1
    )
    verify.assert_called_once_with(operator, confirm_poc=True)
    assert (tmp_path / "operation-result.json").exists() is archive_verified


@pytest.mark.parametrize(
    "next_page,allowed",
    [
        ("https://prices.azure.com/api/retail/prices?$skip=1000", True),
        ("https://prices.azure.com:443/api/retail/prices?$skip=1000", True),
        ("http://prices.azure.com/api/retail/prices?$skip=1000", False),
        ("https://prices.azure.com:444/api/retail/prices?$skip=1000", False),
        ("https://prices.azure.com.example.invalid/api/retail/prices?$skip=1000", False),
        ("https://example@prices.azure.com/api/retail/prices?$skip=1000", False),
        ("https://prices.azure.com/api/retail/prices/extra?$skip=1000", False),
    ],
)
def test_price_pagination_accepts_only_same_https_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, next_page: str, allowed: bool
) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = [
        httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", "https://prices.azure.com/api/retail/prices"),
        )
        for payload in (
            {"Items": [{"retailPrice": 1}], "NextPageLink": next_page},
            {"Items": [{"retailPrice": 2}], "NextPageLink": None},
        )
    ]
    monkeypatch.setattr(cli.httpx, "Client", lambda **_: client)
    operator = Mock(config=configuration(), output=tmp_path)
    if allowed:
        cli.price_inputs(operator)
        assert client.get.call_count == 2
        assert (tmp_path / "cost-inputs.json").is_file()
    else:
        with pytest.raises(OperationError, match="pagination origin"):
            cli.price_inputs(operator)
        assert client.get.call_count == 1


def test_business_critical_requires_its_actual_capability() -> None:
    data = capabilities()
    edition = data["supportedServerVersions"][0]["supportedEditions"][0]
    edition["name"] = "BusinessCritical"
    edition["supportedServiceLevelObjectives"][0]["name"] = "BC_Gen5_2"
    assert validate_capability(data, "Provisioned", 2, 0.5, -1, edition="BusinessCritical")
    with pytest.raises(OperationError, match="not available"):
        validate_capability(data, "Provisioned", 2, 0.5, -1)


def test_visible_capability_is_not_available() -> None:
    with pytest.raises(OperationError, match="not available"):
        validate_capability(capabilities("Visible"), "Serverless", 4, 0.5, -1)


@pytest.mark.parametrize("pause,valid", [(-1, True), (15, True), (14, False), (10081, False)])
def test_actual_serverless_auto_pause_limits(pause: int, valid: bool) -> None:
    if valid:
        assert validate_capability(capabilities(), "Serverless", 4, 0.5, pause)
    else:
        with pytest.raises(OperationError, match="auto-pause"):
            validate_capability(capabilities(), "Serverless", 4, 0.5, pause)


def test_min_capacity_and_zones_not_assumed() -> None:
    with pytest.raises(OperationError, match="minimum"):
        validate_capability(capabilities(), "Serverless", 4, 0.75, -1)
    data = capabilities()
    data["supportedServerVersions"][0]["supportedEditions"][0]["supportedServiceLevelObjectives"][
        0
    ]["zoneRedundant"] = False
    with pytest.raises(OperationError, match="Zone"):
        validate_capability(data, "Serverless", 4, 0.5, -1, True)


@pytest.mark.parametrize(
    "tags",
    [
        {},
        {"poc": "sql-vcore"},
        {"environment": "poc"},
        {"poc": "sql-vcore", "environment": "production"},
    ],
)
def test_exact_dual_tag_guard(tags: dict[str, str]) -> None:
    with pytest.raises(OperationError, match="tags required"):
        require_tags({"tags": tags})


def test_cli_failure_redacts_raw_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(azure.shutil, "which", lambda _: "az")
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="sensitive connection data",
        )
    )
    monkeypatch.setattr(azure.subprocess, "run", run)
    runner = AzureCLI(configuration(), tmp_path)
    with pytest.raises(OperationError) as error:
        runner.run("group", "show", "-n", "synthetic")
    assert "sensitive connection data" not in str(error.value)
    assert "sensitive connection data" in (tmp_path / "cli-001.json").read_text()
    command = run.call_args.args[0]
    assert command[command.index("--subscription") + 1] == str(UUID(int=1))
    assert run.call_args.kwargs.get("shell", False) is False


def test_all_mutations_require_confirmation_before_config_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "output_directory", lambda _: tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    load = Mock(side_effect=AssertionError("Should not load config before guard"))
    monkeypatch.setattr(cli, "load_config", load)
    for name in [
        "deploy",
        "bootstrap",
        "smoke",
        "scale",
        "switch-compute-tier",
        "failover-test",
        "restore-test",
        "destroy",
    ]:
        assert cli.main([name, "--config", "missing.local.json"]) == 1
    load.assert_not_called()


def test_destroy_requires_extra_flag_before_cloud_access() -> None:
    runner = Mock(spec=AzureCLI)
    with pytest.raises(OperationError, match="allow-destructive"):
        cli.destroy(runner, argparse.Namespace(allow_destructive_tests=False))
    runner.require_poc.assert_not_called()


def test_scaling_rejects_unbounded_compute_before_cloud_access() -> None:
    runner = Mock(spec=AzureCLI)
    with pytest.raises(OperationError):
        change_compute(runner, tier="Provisioned", vcores=128, minimum=0.5, pause=-1)
    runner.require_poc.assert_not_called()


def test_baseline_parameters_preserve_fair_comparison() -> None:
    parameters = cli.bicep_parameters(configuration(), False)["parameters"]
    assert parameters["sqlComputeTier"]["value"] == "Provisioned"
    assert parameters["sqlVcores"]["value"] == 2
    assert parameters["sqlMaxSizeGb"]["value"] == 5
    assert parameters["deployApplication"]["value"] is False
    assert parameters["image"]["value"] == ""
    assert "internalApiToken" not in parameters


def test_azure_cli_does_not_inherit_interactive_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(azure.shutil, "which", lambda _: "az")
    execute = Mock(return_value=subprocess.CompletedProcess(["az"], 0, "{}", ""))
    monkeypatch.setattr(azure.subprocess, "run", execute)
    assert AzureCLI(configuration(), tmp_path).run("account", "show") == {}
    assert execute.call_args.kwargs["stdin"] == subprocess.DEVNULL


def test_deployment_uses_the_compiled_and_linted_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = Mock(config=configuration(), output=tmp_path)
    runner.run.return_value = False
    monkeypatch.setattr(cli, "check_capabilities", Mock())
    phase = Mock()
    monkeypatch.setattr(cli, "deploy_phase", phase)
    cli.deploy(runner, tmp_path / "synthetic.local.json", what_if_only=True)
    compiled = tmp_path / "compiled-template.json"
    phase.assert_called_once_with(runner, compiled, False, what_if_only=True)
    build = next(
        call.args for call in runner.run.call_args_list if call.args[:2] == ("bicep", "build")
    )
    assert build[build.index("--outfile") + 1] == str(compiled)


@pytest.mark.parametrize("fail", [False, True])
def test_deploy_token_is_ephemeral_and_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail: bool
) -> None:
    import json

    monkeypatch.setattr(azure.shutil, "which", lambda _: "az")
    runner = AzureCLI(configuration(), tmp_path)
    paths: list[Path] = []
    tokens: list[str] = []

    def execute(*args: str, **kwargs: Any) -> dict[str, Any]:
        assert "--no-prompt" in args
        path = Path(args[args.index("--parameters") + 1][1:])
        parameters = json.loads(path.read_text())["parameters"]
        token = parameters["internalApiToken"]["value"]
        assert len(token) >= 32
        assert token not in args
        assert runner.redact(token) == "[REDACTED]"
        paths.append(path)
        tokens.append(token)
        if fail:
            raise OperationError("synthetic deployment failure")
        return {"properties": {"outputs": {}}}

    monkeypatch.setattr(runner, "run", execute)
    if fail:
        with pytest.raises(OperationError, match="synthetic"):
            cli.deploy_phase(runner, tmp_path / "main.bicep", True, what_if_only=False)
    else:
        cli.deploy_phase(runner, tmp_path / "main.bicep", True, what_if_only=False)
    assert paths and all(not path.exists() for path in paths)
    assert runner.redactions == []
    for artifact in tmp_path.glob("*.json"):
        assert all(token not in artifact.read_text() for token in tokens)


@pytest.mark.parametrize(
    "poll_origin",
    [
        "http://management.azure.com/operations/test",
        "https://management.azure.com.attacker.invalid/operations/test",
        "https://attacker.invalid/operations/test",
    ],
)
def test_local_failover_does_not_forward_tokens_to_untrusted_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    poll_origin: str,
) -> None:
    credentials = Mock()
    credentials.get_token.return_value.token = "synthetic-test-token"
    monkeypatch.setattr(cli, "AzureCliCredential", Mock(return_value=credentials))
    client = Mock()
    client.post.return_value = httpx.Response(
        202,
        headers={"Azure-AsyncOperation": poll_origin},
        request=httpx.Request("POST", "https://management.azure.com/operations/test"),
    )
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(cli.httpx, "Client", Mock(return_value=context))
    runner = Mock(spec=AzureCLI)
    runner.config = configuration()
    runner.output = tmp_path
    with pytest.raises(OperationError, match="origin"):
        cli.local_failover(runner)
    client.get.assert_not_called()
    credentials.close.assert_called_once()


@pytest.mark.parametrize(
    "state,success",
    [
        ("Succeeded", True),
        ("Failed", False),
        ("unexpected", False),
    ],
)
def test_failover_waits_for_operation_not_just_database_online(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    state: str,
    success: bool,
) -> None:
    credentials = Mock()
    credentials.get_token.return_value.token = "synthetic-test-token"
    monkeypatch.setattr(cli, "AzureCliCredential", Mock(return_value=credentials))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    client = Mock()
    request = httpx.Request("POST", "https://management.azure.com/operations/test")
    client.post.return_value = httpx.Response(
        202,
        headers={"Azure-AsyncOperation": str(request.url)},
        request=request,
    )
    client.get.return_value = httpx.Response(200, json={"status": state}, request=request)
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(cli.httpx, "Client", Mock(return_value=context))
    runner = Mock(spec=AzureCLI)
    runner.config = configuration()
    runner.output = tmp_path
    if success:
        cli.local_failover(runner)
    else:
        with pytest.raises(OperationError):
            cli.local_failover(runner)
    client.get.assert_called_once()
