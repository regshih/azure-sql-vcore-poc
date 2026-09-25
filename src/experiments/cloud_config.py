"""Validated private collection coordinates, never credentials or application secrets."""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID


def environment_configuration() -> dict[str, Any]:
    required = (
        "SQL_RESOURCE_ID",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_CLIENT_ID",
        "LOG_ANALYTICS_WORKSPACE_ID",
        "SQL_SERVER",
        "SQL_DATABASE",
        "POC_REGION",
        "POC_ENVIRONMENT_NAME",
    )
    if any(not os.environ.get(name) for name in required):
        raise ValueError("Cloud collection environment coordinates are incomplete")
    subscription = str(UUID(os.environ["AZURE_SUBSCRIPTION_ID"]))
    identity = str(UUID(os.environ["AZURE_CLIENT_ID"]))
    workspace = str(UUID(os.environ["LOG_ANALYTICS_WORKSPACE_ID"]))
    resource = os.environ["SQL_RESOURCE_ID"]
    match = re.fullmatch(
        r"/subscriptions/([a-f0-9-]{36})/resourceGroups/([A-Za-z0-9_.()-]+)"
        r"/providers/Microsoft\.Sql/servers/([a-z0-9-]+)/databases/([A-Za-z0-9_-]+)",
        resource,
        re.IGNORECASE,
    )
    if not match or str(UUID(match[1])) != subscription:
        raise ValueError("Cloud SQL resource does not match the selected subscription")
    server = os.environ["SQL_SERVER"].lower().removesuffix(".database.windows.net")
    if server != match[3].lower() or os.environ["SQL_DATABASE"] != match[4]:
        raise ValueError("SQL data-plane target does not match the ARM database resource")
    if os.environ.get("POC_RESOURCE_GROUP", match[2]).lower() != match[2].lower():
        raise ValueError("Resource group does not match the ARM database resource")
    region, environment = os.environ["POC_REGION"], os.environ["POC_ENVIRONMENT_NAME"]
    if not re.fullmatch(r"[a-z0-9]+", region) or not re.fullmatch(
        r"[a-z][a-z0-9-]{2,19}", environment
    ):
        raise ValueError("Invalid POC region or environment name")
    return {
        "subscription_id": subscription,
        "resource_group": match[2],
        "environment_name": environment,
        "region": region,
        "sql_server": server,
        "database": match[4],
        "sql_resource_id": resource,
        "workspace_id": workspace,
        "managed_identity_client_id": identity,
        "evidence_storage_account": os.environ.get("EVIDENCE_STORAGE_ACCOUNT"),
        "evidence_storage_container": os.environ.get("EVIDENCE_STORAGE_CONTAINER", "evidence"),
        "credential": "managed-identity",
    }
