"""Private, identity-authenticated raw evidence snapshots; never public publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.identity import AzureCliCredential, DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from src.experiments.common import ROOT, read_json, safe_main, utc_now, write_json

RECEIPT = "cloud-archive-receipt.json"
MANIFEST = "archive-manifest.json"
DOWNLOAD_RECEIPT = "download-verification.json"
MAX_FILES = 10_000
MAX_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 4 * 1024**2


@dataclass(frozen=True)
class StorageSettings:
    account: str
    container: str = "evidence"
    credential: str = "managed-identity"
    client_id: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]{3,24}", self.account):
            raise ValueError("Invalid evidence storage account name")
        if self.container != "evidence":
            raise ValueError("Raw evidence must use the private evidence container")
        if self.credential not in {"managed-identity", "azure-cli"}:
            raise ValueError("Evidence credential must be managed-identity or azure-cli")


def configured_storage(config_path: Path | None = None) -> StorageSettings | None:
    config = read_json(config_path) if config_path else {}
    account = os.environ.get("EVIDENCE_STORAGE_ACCOUNT") or config.get("evidence_storage_account")
    if not account:
        return None
    cloud = bool(os.environ.get("EVIDENCE_STORAGE_ACCOUNT"))
    return StorageSettings(
        account=account,
        container=os.environ.get("EVIDENCE_STORAGE_CONTAINER")
        or config.get("evidence_storage_container")
        or "evidence",
        credential="managed-identity" if cloud else "azure-cli",
        client_id=os.environ.get("AZURE_CLIENT_ID") if cloud else None,
    )


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _credential(settings: StorageSettings) -> DefaultAzureCredential | AzureCliCredential:
    if settings.credential == "azure-cli":
        return AzureCliCredential()
    return DefaultAzureCredential(
        managed_identity_client_id=settings.client_id,
        exclude_environment_credential=True,
        exclude_workload_identity_credential=True,
        exclude_shared_token_cache_credential=True,
        exclude_visual_studio_code_credential=True,
        exclude_cli_credential=True,
        exclude_powershell_credential=True,
        exclude_developer_cli_credential=True,
        exclude_interactive_browser_credential=True,
        exclude_broker_credential=True,
    )


def inventory(directory: Path) -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]]]:
    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        raise ValueError("Evidence source must be a real run directory")
    files: list[tuple[Path, dict[str, Any]]] = []
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Symlinks are not permitted in raw evidence")
        if path.is_dir():
            continue
        if path.name in {RECEIPT, MANIFEST, DOWNLOAD_RECEIPT}:
            continue
        relative = path.relative_to(directory)
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) for part in relative.parts):
            raise ValueError("Unsafe artifact name in run directory")
        if not path.is_file():
            raise ValueError("Raw evidence includes a nonregular file")
        size = path.stat().st_size
        total += size
        if len(files) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError("Evidence snapshot exceeds bounded upload limits")
        files.append((path, {"path": relative.as_posix(), "bytes": size, "sha256": _digest(path)}))
    if not any(
        path.name in {"manifest.json", "matrix-plan.json", "restoration.json"} for path, _ in files
    ):
        raise ValueError("Evidence tree contains no workload or experiment record")
    manifest = {
        "schema_version": 1,
        "classification": "private-raw-evidence",
        "hash_algorithm": "sha256",
        "artifact_count": len(files),
        "total_bytes": total,
        "artifacts": [record for _, record in files],
    }
    return manifest, files


def _upload_one(
    service: BlobServiceClient,
    settings: StorageSettings,
    name: str,
    data: Any,
    size: int,
    digest: str,
    content_type: str,
) -> None:
    blob = service.get_blob_client(container=settings.container, blob=name)
    try:
        blob.upload_blob(
            data,
            length=size,
            overwrite=False,
            metadata={"sha256": digest, "classification": "private-raw-evidence"},
            content_settings=ContentSettings(content_type=content_type),
            max_concurrency=2,
            timeout=120,
            logging_enable=False,
        )
    except ResourceExistsError:
        properties = blob.get_blob_properties(timeout=30, logging_enable=False)
        if properties.size != size or properties.metadata.get("sha256") != digest:
            raise RuntimeError(
                "Existing evidence blob does not match the immutable snapshot"
            ) from None


def _readback(
    service: BlobServiceClient,
    settings: StorageSettings,
    name: str,
    size: int,
    expected_digest: str,
    deadline: float,
    *,
    capture: bool = False,
) -> bytes:
    if time.monotonic() >= deadline:
        raise RuntimeError("Archive readback verification deadline exceeded")
    blob = service.get_blob_client(settings.container, name)
    if blob.get_blob_properties(timeout=30, logging_enable=False).size != size:
        raise RuntimeError("Archive readback length verification failed")
    digest = hashlib.sha256()
    count = 0
    content = bytearray()
    if size:
        for chunk in blob.download_blob(
            offset=0, length=size + 1, max_concurrency=2, timeout=120, logging_enable=False
        ).chunks():
            count += len(chunk)
            if count > size or time.monotonic() >= deadline:
                raise RuntimeError("Archive readback exceeded its length or time bound")
            digest.update(chunk)
            if capture:
                if count > MAX_MANIFEST_BYTES:
                    raise ValueError("Run manifest exceeds verification bound")
                content.extend(chunk)
    if count != size or digest.hexdigest() != expected_digest:
        raise RuntimeError("Archive readback SHA256 verification failed")
    return bytes(content)


def _workload_receipt(content: bytes) -> dict[str, Any] | None:
    if not content:
        return None
    manifest = json.loads(content)
    if not isinstance(manifest, dict):
        raise ValueError("Verified run manifest is invalid")
    result: dict[str, Any] = {}
    for name, pattern in (
        ("test_run_id", r"run-\d{8}T\d{6}Z-[a-f0-9]{12}"),
        ("profile_hash", r"[a-f0-9]{64}"),
        ("workload_profile", r"[a-z0-9-]{1,64}"),
    ):
        value = manifest.get(name)
        result[name] = value if isinstance(value, str) and re.fullmatch(pattern, value) else None
    result["status"] = (
        manifest.get("status")
        if manifest.get("status") in {"completed", "completed-with-request-errors", "failed"}
        else None
    )
    result["evidence_collection_status"] = (
        manifest.get("evidence_collection_status")
        if manifest.get("evidence_collection_status")
        in {"measured", "measured-with-gaps", "incomplete", "failed"}
        else None
    )
    count = manifest.get("sql_business_request_success_count")
    result["sql_business_request_success_count"] = (
        count if type(count) is int and count >= 0 else None
    )
    return result


def upload(directory: Path, settings: StorageSettings) -> dict[str, Any]:
    manifest, files = inventory(directory)
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("Archive manifest exceeds the verified retrieval bound")
    manifest_hash = hashlib.sha256(encoded).hexdigest()
    run_id = ""
    if (directory / "manifest.json").is_file():
        run_id = str(read_json(directory / "manifest.json").get("test_run_id", ""))
    if not re.fullmatch(r"run-\d{8}T\d{6}Z-[a-f0-9]{12}", run_id):
        run_id = "bundle-" + manifest_hash[:20]
    prefix = f"runs/{run_id}/{manifest_hash[:16]}"
    credential = _credential(settings)
    with (
        credential,
        BlobServiceClient(
            account_url=f"https://{settings.account}.blob.core.windows.net",
            credential=credential,
            retry_total=3,
            connection_timeout=15,
            read_timeout=120,
            logging_enable=False,
        ) as service,
    ):
        properties = service.get_container_client(settings.container).get_container_properties()
        if properties.public_access:
            raise ValueError("Refusing to upload raw evidence to a public container")
        for path, record in files:
            if path.stat().st_size != record["bytes"] or _digest(path) != record["sha256"]:
                raise RuntimeError("Evidence changed during snapshot creation")
            with path.open("rb") as stream:
                _upload_one(
                    service,
                    settings,
                    prefix + "/" + record["path"],
                    stream,
                    record["bytes"],
                    record["sha256"],
                    "application/octet-stream",
                )
            if _digest(path) != record["sha256"]:
                raise RuntimeError("Evidence changed during upload; snapshot is incomplete")
        deadline = time.monotonic() + 600
        workload_content = b""
        for _, record in files:
            capture = record["path"] == "manifest.final.json"
            content = _readback(
                service,
                settings,
                prefix + "/" + record["path"],
                record["bytes"],
                record["sha256"],
                deadline,
                capture=capture,
            )
            if capture:
                workload_content = content
        workload = _workload_receipt(workload_content)
        # Completion requires full artifact readback, not trusted SHA metadata.
        _upload_one(
            service,
            settings,
            prefix + "/" + MANIFEST,
            encoded,
            len(encoded),
            manifest_hash,
            "application/json",
        )
        _readback(
            service,
            settings,
            prefix + "/" + MANIFEST,
            len(encoded),
            manifest_hash,
            deadline,
        )
    receipt = {
        "status": "uploaded",
        "classification": "private-raw-evidence",
        "completed_utc": utc_now(),
        "blob_prefix": prefix,
        "manifest_blob": prefix + "/" + MANIFEST,
        "manifest_sha256": manifest_hash,
        "artifact_count": len(files),
        "total_bytes": manifest["total_bytes"],
        "credential": settings.credential,
        "public_publication": False,
        "artifacts": manifest["artifacts"],
        "verification": {
            "status": "verified",
            "method": "blob-readback-sha256",
            "verified_utc": utc_now(),
            "artifact_count": len(files),
            "total_bytes": manifest["total_bytes"],
            "manifest_sha256": manifest_hash,
            "credential": settings.credential,
            "operator_download_verified": False,
        },
        "workload": workload,
    }
    write_json(directory / RECEIPT, receipt)
    for record in manifest["artifacts"]:
        print(
            "POC_EVIDENCE " + json.dumps({"blob_prefix": prefix, **record, "status": "uploaded"}),
            flush=True,
        )
    print(
        "POC_EVIDENCE_UPLOAD "
        + json.dumps(
            {key: value for key, value in receipt.items() if key != "artifacts"},
            separators=(",", ":"),
        ),
        flush=True,
    )
    return receipt


def persistence_failure(directory: Path, exc: Exception) -> None:
    receipt = {
        "status": "private-evidence-persistence-failed",
        "failure_category": type(exc).__name__,
        "completed_utc": utc_now(),
        "complete_snapshot_confirmed": False,
    }
    write_json(directory / RECEIPT, receipt)
    print("POC_EVIDENCE " + json.dumps(receipt), flush=True)


def archive_if_configured(directory: Path, config_path: Path | None = None) -> None:
    try:
        settings = configured_storage(config_path)
        if settings is None:
            if os.environ.get("CONTAINER_APP_JOB_NAME"):
                raise RuntimeError("Cloud runner evidence destination is not configured")
            return
        upload(directory, settings)
    except Exception as exc:
        persistence_failure(directory, exc)
        raise RuntimeError(
            "Private evidence upload failed; retain local artifacts and retry"
        ) from exc


def download(
    directory: Path,
    settings: StorageSettings,
    prefix: str,
    expected_manifest_hash: str,
) -> None:
    if not re.fullmatch(
        r"runs/(?:run-\d{8}T\d{6}Z-[a-f0-9]{12}|bundle-[a-f0-9]{20})/[a-f0-9]{16}",
        prefix,
    ) or not re.fullmatch(r"[a-f0-9]{64}", expected_manifest_hash):
        raise ValueError("Use the exact safe prefix and manifest SHA256 from the upload receipt")
    if prefix.rsplit("/", 1)[-1] != expected_manifest_hash[:16]:
        raise ValueError("Snapshot prefix does not match the expected manifest hash")
    if directory.exists() or directory.is_symlink():
        raise FileExistsError("Download destination must not exist")
    credential = _credential(settings)
    with (
        credential,
        BlobServiceClient(
            account_url=f"https://{settings.account}.blob.core.windows.net",
            credential=credential,
            retry_total=3,
            connection_timeout=15,
            read_timeout=120,
            logging_enable=False,
        ) as service,
    ):
        marker = service.get_blob_client(settings.container, prefix + "/" + MANIFEST)
        marker_properties = marker.get_blob_properties(timeout=30, logging_enable=False)
        if marker_properties.size > MAX_MANIFEST_BYTES:
            raise ValueError("Archive manifest exceeds the download bound")
        encoded = marker.download_blob(
            offset=0, length=MAX_MANIFEST_BYTES + 1, logging_enable=False
        ).readall()
        if hashlib.sha256(encoded).hexdigest() != expected_manifest_hash:
            raise ValueError("Archive manifest hash does not match the upload receipt")
        manifest = json.loads(encoded)
        records = manifest.get("artifacts", [])
        if (
            manifest.get("classification") != "private-raw-evidence"
            or not isinstance(records, list)
            or not 0 < len(records) <= MAX_FILES
            or manifest.get("artifact_count") != len(records)
        ):
            raise ValueError("Invalid raw evidence archive manifest")
        total = 0
        names: set[str] = set()
        for record in records:
            name = record.get("path", "")
            if (
                not isinstance(name, str)
                or not name
                or any(
                    part in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part)
                    for part in name.split("/")
                )
                or name.casefold() in names
                or not isinstance(record.get("bytes"), int)
                or record["bytes"] < 0
                or not re.fullmatch(r"[a-f0-9]{64}", record.get("sha256", ""))
            ):
                raise ValueError("Invalid or unsafe artifact entry")
            names.add(name.casefold())
            total += record["bytes"]
            if total > MAX_BYTES:
                raise ValueError("Archive exceeds the download bound")
        if total != manifest.get("total_bytes"):
            raise ValueError("Archive size differs from the declared total")
        directory.mkdir(parents=True)
        try:
            for record in records:
                path = directory.joinpath(*record["path"].split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                blob = service.get_blob_client(settings.container, prefix + "/" + record["path"])
                with path.open("xb") as stream:
                    if record["bytes"]:
                        blob.download_blob(
                            offset=0,
                            length=record["bytes"] + 1,
                            max_concurrency=2,
                            timeout=120,
                            logging_enable=False,
                        ).readinto(stream)
                    elif blob.get_blob_properties(timeout=30, logging_enable=False).size != 0:
                        raise ValueError("Empty artifact length verification failed")
                if path.stat().st_size != record["bytes"] or _digest(path) != record["sha256"]:
                    raise ValueError("Downloaded artifact failed length or SHA256 verification")
            (directory / MANIFEST).write_bytes(encoded)
            write_json(
                directory / DOWNLOAD_RECEIPT,
                {
                    "status": "downloaded-and-verified",
                    "completed_utc": utc_now(),
                    "blob_prefix": prefix,
                    "manifest_sha256": expected_manifest_hash,
                    "artifact_count": len(records),
                    "total_bytes": total,
                    "artifacts": records,
                    "credential": settings.credential,
                    "public_publication": False,
                },
            )
        except Exception:
            shutil.rmtree(directory)
            raise
    print(
        "POC_EVIDENCE_DOWNLOAD "
        + json.dumps(
            {
                "status": "downloaded-and-verified",
                "artifact_count": len(records),
                "manifest_sha256": expected_manifest_hash,
                "public_publication": False,
            }
        ),
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload or retrieve verified private raw evidence")
    parser.add_argument("--run-dir", "--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--credential", choices=["managed-identity", "azure-cli"])
    retrieval = parser.add_mutually_exclusive_group()
    retrieval.add_argument("--download-prefix")
    retrieval.add_argument("--run-id")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args(argv)
    settings = configured_storage(args.config)
    if settings is None:
        parser.error("Configure EVIDENCE_STORAGE_ACCOUNT or evidence_storage_account in --config")
    if args.credential:
        settings = StorageSettings(
            settings.account, settings.container, args.credential, settings.client_id
        )
    if args.download_prefix or args.run_id:
        if not args.manifest_sha256:
            parser.error("Retrieval requires --manifest-sha256 from the upload receipt")
        destination = args.run_dir.resolve()
        raw_root = (ROOT / "results" / "local-untracked-runs").resolve()
        if destination == raw_root or not destination.is_relative_to(raw_root):
            parser.error("Private downloads must use --output under results/local-untracked-runs")
        if settings.credential != "azure-cli":
            parser.error("Operator retrieval requires --credential azure-cli and read-only access")
        prefix = args.download_prefix or f"runs/{args.run_id}/{args.manifest_sha256[:16]}"
        download(destination, settings, prefix, args.manifest_sha256)
    else:
        if args.manifest_sha256:
            parser.error("--manifest-sha256 requires --download-prefix")
        try:
            upload(args.run_dir, settings)
        except Exception as exc:
            persistence_failure(args.run_dir, exc)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
