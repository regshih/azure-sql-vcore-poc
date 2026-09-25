from uuid import UUID

import pytest

from src.experiments.cloud_config import environment_configuration


def set_environment(monkeypatch):
    subscription, workspace, identity = (str(UUID(int=n)) for n in (1, 2, 3))
    values = {
        "AZURE_SUBSCRIPTION_ID": subscription,
        "AZURE_CLIENT_ID": identity,
        "LOG_ANALYTICS_WORKSPACE_ID": workspace,
        "SQL_RESOURCE_ID": f"/subscriptions/{subscription}/resourceGroups/rg-synthetic"
        "/providers/Microsoft.Sql/servers/synthetic-server/databases/poc",
        "SQL_SERVER": ".".join(("synthetic-server", "database.windows.net")),
        "SQL_DATABASE": "poc",
        "POC_REGION": "eastus",
        "POC_RESOURCE_GROUP": "rg-synthetic",
        "POC_ENVIRONMENT_NAME": "synthetic",
        "POC_INTERNAL_API_TOKEN": "never-copy-the-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_private_environment_config_matches_targets_and_excludes_all_secrets(monkeypatch):
    set_environment(monkeypatch)
    config = environment_configuration()
    assert config["sql_server"] == "synthetic-server"
    assert config["database"] == "poc"
    assert config["credential"] == "managed-identity"
    assert config["region"] == "eastus"
    assert "never-copy-the-secret" not in str(config)
    assert not any("token" in key or "secret" in key for key in config)


@pytest.mark.parametrize(
    "name,value",
    [
        ("SQL_SERVER", ".".join(("other", "database.windows.net"))),
        ("SQL_DATABASE", "other"),
        ("POC_RESOURCE_GROUP", "rg-other"),
        ("POC_REGION", "untrusted'value"),
        ("AZURE_SUBSCRIPTION_ID", str(UUID(int=4))),
        ("AZURE_CLIENT_ID", ""),
        ("POC_ENVIRONMENT_NAME", ""),
        ("POC_ENVIRONMENT_NAME", "ab"),
        ("POC_ENVIRONMENT_NAME", "a" * 21),
    ],
)
def test_cloud_config_rejects_ambiguous_or_mismatched_resources(monkeypatch, name, value):
    set_environment(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        environment_configuration()


@pytest.mark.parametrize("environment", ["abc", "a" * 20])
def test_environment_name_supported_boundaries(monkeypatch, environment):
    set_environment(monkeypatch)
    monkeypatch.setenv("POC_ENVIRONMENT_NAME", environment)
    assert environment_configuration()["environment_name"] == environment
