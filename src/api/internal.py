import hmac
import ipaddress
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.database.models import Department
from src.database.runtime import RuntimeRepository

router = APIRouter()


def authorized_internal(request: Request) -> RuntimeRepository:
    runtime = cast(RuntimeRepository, request.app.state.runtime)
    settings = runtime.settings
    supplied = request.headers.get("authorization", "")
    expected = settings.internal_api_token
    try:
        address = ipaddress.ip_address(request.client.host if request.client else "")
        internal = any(
            address in ipaddress.ip_network(network)
            for network in settings.internal_allowed_networks
        )
    except ValueError:
        internal = False
    if (
        not internal
        or expected is None
        or not hmac.compare_digest(
            supplied.encode(), ("Bearer " + expected.get_secret_value()).encode()
        )
    ):
        raise HTTPException(status_code=403, detail="internal_access_required")
    return runtime


InternalRuntime = Annotated[RuntimeRepository, Depends(authorized_internal)]


class MaintenanceRequest(BaseModel):
    action: Literal["idle", "resume"]
    confirm: Literal[True]


class PoolDisposalRequest(BaseModel):
    confirm: Literal[True]


class DiagnosticRequest(BaseModel):
    allow_unsafe_test: Literal[True]
    department: Department = "operations"
    delay_seconds: int = Field(default=0, ge=0, le=30)
    poor_pooling: bool = False


class RuntimeConfigurationRequest(BaseModel):
    cache_enabled: bool
    expected_version: int = Field(ge=0)
    confirm: Literal[True]


@router.get("/internal/metadata", include_in_schema=False)
def metadata(runtime: InternalRuntime, refresh_database: bool = False) -> dict[str, Any]:
    return runtime.refresh_metadata() if refresh_database else runtime.metadata()


@router.get("/internal/config", include_in_schema=False)
def configuration(runtime: InternalRuntime) -> dict[str, Any]:
    return runtime.configuration()


@router.put("/internal/config", include_in_schema=False)
async def configure(
    request: RuntimeConfigurationRequest, runtime: InternalRuntime
) -> dict[str, Any]:
    try:
        return await runtime.configure_cache(request.cache_enabled, request.expected_version)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.get("/internal/metrics", include_in_schema=False)
def metrics(runtime: InternalRuntime) -> dict[str, Any]:
    return runtime.snapshot()


@router.post("/internal/maintenance", include_in_schema=False)
async def maintenance(request: MaintenanceRequest, runtime: InternalRuntime) -> dict[str, Any]:
    if request.action == "idle":
        await runtime.enter_idle()
    else:
        await runtime.resume()
    return {
        "status": "idle" if runtime.idle else "active",
        "pool_disposed": runtime.idle,
        "readiness_mode": "process" if runtime.idle else runtime.settings.readiness_mode,
    }


@router.post("/api/diagnostics/query")
def diagnostic(request: DiagnosticRequest, runtime: InternalRuntime) -> dict[str, Any]:
    if not runtime.settings.poc_mode or not runtime.settings.allow_unsafe_tests:
        raise HTTPException(status_code=403, detail="unsafe_tests_disabled")
    return runtime.diagnostic(request.department, request.delay_seconds, request.poor_pooling)


@router.post("/admin/pool/dispose", include_in_schema=False)
async def dispose_pool(request: PoolDisposalRequest, runtime: InternalRuntime) -> dict[str, Any]:
    if not runtime.settings.poc_mode or not runtime.settings.allow_unsafe_tests:
        raise HTTPException(status_code=403, detail="unsafe_tests_disabled")
    await runtime.enter_idle()
    return {
        "status": "idle",
        "pool_disposed": True,
        "readiness_mode": "process",
        "admission_suspended": True,
        "instance_id": runtime.instance_id,
        "resume_endpoint": "/internal/maintenance",
    }
