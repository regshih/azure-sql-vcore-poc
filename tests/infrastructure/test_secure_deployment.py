from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compiled(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    executable = shutil.which("az")
    if not executable:
        pytest.skip("Azure CLI unavailable; strict validator separately requires Bicep.")
    output = tmp_path_factory.mktemp("bicep-contract") / "main.json"
    result = subprocess.run(
        [
            executable,
            "bicep",
            "build",
            "--file",
            str(ROOT / "infra" / "bicep" / "main.bicep"),
            "--outfile",
            str(output),
            "--only-show-errors",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    return document


def module(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in document["resources"] if item["name"] == name)


def resources(document: dict[str, Any], name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = module(document, name)["properties"]["template"]["resources"]
    return result


def test_private_networking_and_entra_only_sql(compiled: dict[str, Any]) -> None:
    assert compiled["parameters"]["deploymentProfile"]["defaultValue"] == "secure"
    assert compiled["parameters"]["allowEvaluationPublicAccess"]["defaultValue"] is False
    environment = module(compiled, "app-environment")
    assert environment["properties"]["parameters"]["internal"]["value"] == (
        "[not(variables('publicEvaluation'))]"
    )
    expression = compiled["variables"]["publicEvaluation"]
    assert "allowEvaluationPublicAccess" in expression and "evaluationIp" in expression
    sql = resources(compiled, "sql-primary")
    server = next(item for item in sql if item["type"] == "Microsoft.Sql/servers")
    assert server["properties"]["administrators"]["azureADOnlyAuthentication"] is True
    assert "administratorLoginPassword" not in server["properties"]
    assert "'Enabled', 'Disabled'" in server["properties"]["publicNetworkAccess"]
    endpoint = next(item for item in sql if item["type"].endswith("/privateDnsZoneGroups"))
    assert endpoint["properties"]["privateDnsZoneConfigs"][0]["properties"]["privateDnsZoneId"] == (
        "[parameters('privateDnsZoneId')]"
    )


def test_shared_phase_has_no_placeholder_apps_or_jobs(compiled: dict[str, Any]) -> None:
    for name in ("api", "jobs"):
        assert module(compiled, name)["condition"] == "[parameters('deployApplication')]"
    jobs = resources(compiled, "jobs")
    assert len(jobs) == 2
    assert all(item["type"] == "Microsoft.App/jobs" for item in jobs)
    assert all(item["properties"]["configuration"]["triggerType"] == "Manual" for item in jobs)
    assert all(item["properties"]["configuration"]["replicaRetryLimit"] == 0 for item in jobs)
    assert "helloworld" not in json.dumps(compiled)
    assert compiled["parameters"]["internalApiToken"]["type"] == "securestring"


def test_sql_dns_suffix_already_includes_separator(compiled: dict[str, Any]) -> None:
    zone = next(
        item
        for item in resources(compiled, "network")
        if item["type"] == "Microsoft.Network/privateDnsZones"
        and "sqlServerHostname" in item["name"]
    )
    assert zone["name"] == "[format('privatelink{0}', environment().suffixes.sqlServerHostname)]"
    outputs = module(compiled, "failover-group")["properties"]["template"]["outputs"]
    assert "format('{0}{1}'," in outputs["readWriteHost"]["value"]
    assert "format('{0}.secondary{1}'," in outputs["readOnlyHost"]["value"]


def test_role_assignments_are_resource_scoped_and_not_sql_data_grants(
    compiled: dict[str, Any],
) -> None:
    assignments = resources(compiled, "roles")
    assert len(assignments) == 4
    assert all(item["scope"].startswith("[resourceId(") for item in assignments)
    assert all("resourceGroups" not in item["scope"] for item in assignments)
    roles = module(compiled, "roles")["properties"]["template"]["variables"]
    assert set(roles) == {"acrPull", "blobContributor", "reader", "logReader"}
    pulls = assignments[0]["copy"]["count"]
    for name in ("runtimePrincipalId", "bootstrapPrincipalId", "runnerPrincipalId"):
        assert name in pulls
    assert "blobServices/containers" in assignments[1]["scope"]
    assert "Microsoft.KeyVault" not in json.dumps(compiled)


def test_blob_security_and_managed_identity_client_ids(compiled: dict[str, Any]) -> None:
    storage = next(
        item
        for item in resources(compiled, "evidence")
        if item["type"] == "Microsoft.Storage/storageAccounts"
    )["properties"]
    assert storage["allowSharedKeyAccess"] is False
    assert storage["allowBlobPublicAccess"] is False
    assert storage["publicNetworkAccess"] == "Disabled"
    assert storage["supportsHttpsTrafficOnly"] is True
    assert "httpsTrafficOnly" not in storage
    app = resources(compiled, "api")[0]
    environment = app["properties"]["template"]["containers"][0]["env"]
    # Bicep inlines the array because Application Insights is a runtime reference.
    assert "createObject('name','AZURE_CLIENT_ID','value',parameters('runtimeClientId'))" in (
        environment.replace(" ", "")
    )
    identities = module(compiled, "identities")["properties"]["template"]["outputs"]
    assert identities["runtimeIdentityClientId"]["value"].endswith(".clientId]")
    assert identities["runtimeIdentityPrincipalId"]["value"].endswith(".principalId]")


def test_optional_dr_is_real_and_disabled_by_default(compiled: dict[str, Any]) -> None:
    assert compiled["parameters"]["enableDr"]["defaultValue"] is False
    for name in ("sql-secondary", "failover-group"):
        assert module(compiled, name)["condition"] == "[parameters('enableDr')]"
    group = resources(compiled, "failover-group")[0]
    assert group["type"] == "Microsoft.Sql/servers/failoverGroups"
    assert group["properties"]["readWriteEndpoint"]["failoverPolicy"] == "Manual"


def test_optional_cache_is_private_passwordless_and_opt_in(compiled: dict[str, Any]) -> None:
    assert compiled["parameters"]["enableLegacyRedis"]["defaultValue"] is False
    extension = module(compiled, "legacy-redis-extension")
    assert extension["condition"] == "[parameters('enableLegacyRedis')]"
    cache = next(
        item
        for item in resources(compiled, "legacy-redis-extension")
        if item["type"] == "Microsoft.Cache/redis"
    )["properties"]
    assert cache["disableAccessKeyAuthentication"] is True
    assert cache["publicNetworkAccess"] == "Disabled"
    assert cache["enableNonSslPort"] is False
    assert compiled["parameters"]["enableBusinessCritical"]["defaultValue"] is False


def test_all_alert_signals_are_templates_not_active_paging(compiled: dict[str, Any]) -> None:
    assert compiled["parameters"]["enableAlerts"]["defaultValue"] is False
    template = module(compiled, "alerts")["properties"]["template"]
    assert len(template["variables"]["metricSignals"]) == 9
    assert len(template["variables"]["appSignals"]) == 3
    alerts = template["resources"]
    assert len([item for item in alerts if item["type"].endswith("/activityLogAlerts")]) == 2
    assert all(item["properties"]["enabled"] == "[parameters('enabled')]" for item in alerts)
    assert template["parameters"]["actionGroupIds"]["defaultValue"] == []
    log_rules = next(item for item in alerts if item["type"].endswith("/scheduledQueryRules"))
    assert log_rules["condition"] == "[parameters('enabled')]"
