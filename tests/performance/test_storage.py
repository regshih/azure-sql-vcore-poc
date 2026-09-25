import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobClient

from src.experiments import storage
from src.experiments.common import read_json, write_json


@pytest.fixture
def blob_store(monkeypatch):
    state = SimpleNamespace(
        blobs={},
        order=[],
        public=False,
        fail_on=None,
        downloads=[],
        corrupt_read=None,
        denied_read=None,
    )
    service = MagicMock()
    service.__enter__.return_value = service
    service.get_container_client.return_value.get_container_properties.side_effect = lambda: (
        SimpleNamespace(public_access="blob" if state.public else None)
    )

    def get_blob(container=None, blob=None):
        assert container == "evidence"
        client = MagicMock()

        def upload(data, **kwargs):
            if state.fail_on == blob:
                raise OSError("simulated transport failure")
            if blob in state.blobs:
                raise ResourceExistsError("already uploaded")
            content = data if isinstance(data, bytes) else data.read()
            assert kwargs["overwrite"] is False
            assert kwargs["logging_enable"] is False
            state.blobs[blob] = (content, kwargs["metadata"])
            state.order.append(blob)

        def props(**kwargs):
            data, metadata = state.blobs[blob]
            return SimpleNamespace(size=len(data), metadata=metadata)

        def download(**kwargs):
            assert kwargs["offset"] == 0
            state.downloads.append(blob)
            if state.denied_read and blob.endswith(state.denied_read):
                raise OSError("read permission denied")
            content = state.blobs[blob][0][: kwargs.get("length")]
            if state.corrupt_read and blob.endswith(state.corrupt_read):
                content = b"x" * len(content)
            return SimpleNamespace(
                readall=lambda: content,
                readinto=lambda stream: stream.write(content),
                chunks=lambda: iter([content]),
            )

        client.upload_blob.side_effect = upload
        client.get_blob_properties.side_effect = props
        client.download_blob.side_effect = download
        return client

    service.get_blob_client.side_effect = get_blob
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(storage, "BlobServiceClient", factory)
    state.factory = factory
    state.identity = MagicMock()
    monkeypatch.setattr(storage, "DefaultAzureCredential", state.identity)
    monkeypatch.setattr(storage, "AzureCliCredential", MagicMock())
    return state


def raw_run(workdir):
    run = workdir / "raw"
    write_json(
        run / "manifest.json",
        {"test_run_id": "run-20260925T060000Z-" + "a" * 12, "status": "completed"},
    )
    (run / "requests.jsonl").write_text('{"elapsed_ms":7}\n', encoding="utf-8")
    return run


def test_upload_all_artifacts_manifest_last_and_idempotent(workdir, blob_store, capsys):
    run = raw_run(workdir)
    settings = storage.StorageSettings("syntheticevidence", client_id="client-reference")
    receipt = storage.upload(run, settings)
    assert receipt["artifact_count"] == 2
    assert receipt["verification"]["method"] == "blob-readback-sha256"
    assert receipt["verification"]["artifact_count"] == receipt["artifact_count"]
    assert receipt["verification"]["manifest_sha256"] == receipt["manifest_sha256"]
    assert receipt["verification"]["operator_download_verified"] is False
    assert set(blob_store.downloads) == set(blob_store.blobs)
    assert blob_store.order[-1].endswith("/archive-manifest.json")
    marker = blob_store.blobs[receipt["manifest_blob"]][0]
    assert hashlib.sha256(marker).hexdigest() == receipt["manifest_sha256"]
    manifest = json.loads(marker)
    assert manifest["total_bytes"] == sum(x["bytes"] for x in manifest["artifacts"])
    assert all(x["sha256"] for x in manifest["artifacts"])
    assert storage.upload(run, settings)["blob_prefix"] == receipt["blob_prefix"]
    assert len(blob_store.order) == 3
    assert blob_store.identity.call_args.kwargs["managed_identity_client_id"] == "client-reference"
    assert blob_store.identity.call_args.kwargs["exclude_environment_credential"] is True
    assert blob_store.identity.call_args.kwargs["exclude_cli_credential"] is True
    output = capsys.readouterr().out
    assert "syntheticevidence" not in output
    assert "client-reference" not in output
    assert "elapsed_ms" not in output
    assert "POC_EVIDENCE_UPLOAD" in output
    assert "account_key" not in blob_store.factory.call_args.kwargs
    artifact_receipts = [
        json.loads(line.removeprefix("POC_EVIDENCE "))
        for line in output.splitlines()
        if line.startswith("POC_EVIDENCE ")
    ]
    assert {(item["path"], item["sha256"], item["blob_prefix"]) for item in artifact_receipts} == {
        (item["path"], item["sha256"], receipt["blob_prefix"]) for item in manifest["artifacts"]
    }


def test_public_container_refused(workdir, blob_store):
    blob_store.public = True
    with pytest.raises(ValueError, match="public container"):
        storage.upload(raw_run(workdir), storage.StorageSettings("syntheticevidence"))
    assert not blob_store.blobs


@pytest.mark.parametrize("filename", ["requests.jsonl", "archive-manifest.json"])
@pytest.mark.parametrize("failure", ["corrupt_read", "denied_read"])
def test_upload_fails_without_full_remote_readback(
    workdir, blob_store, monkeypatch, capsys, filename, failure
):
    run = raw_run(workdir)
    setattr(blob_store, failure, filename)
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticevidence")
    with pytest.raises(RuntimeError, match="Private evidence upload failed"):
        storage.archive_if_configured(run)
    assert read_json(run / storage.RECEIPT)["complete_snapshot_confirmed"] is False
    assert "POC_EVIDENCE_UPLOAD " not in capsys.readouterr().out
    if filename != "archive-manifest.json":
        assert not any(name.endswith("/archive-manifest.json") for name in blob_store.blobs)


def test_readback_checks_existing_bytes_not_just_size_and_hash_metadata(workdir, blob_store):
    run = raw_run(workdir)
    settings = storage.StorageSettings("syntheticevidence")
    receipt = storage.upload(run, settings)
    name = receipt["blob_prefix"] + "/requests.jsonl"
    original, metadata = blob_store.blobs[name]
    blob_store.blobs[name] = (b"x" * len(original), metadata)
    with pytest.raises(RuntimeError, match="SHA256"):
        storage.upload(run, settings)


def test_workload_receipt_comes_from_verified_final_manifest_only(workdir, blob_store):
    from src.experiments.profiles import load_profile

    run = raw_run(workdir)
    final = {
        **read_json(run / "manifest.json"),
        "workload_profile": "smoke",
        "profile_hash": load_profile("smoke").profile_hash,
        "evidence_collection_status": "measured",
        "sql_business_request_success_count": 1,
        "private_value": "never-in-public-receipt",
    }
    write_json(run / "manifest.final.json", final)
    receipt = storage.upload(run, storage.StorageSettings("syntheticevidence"))
    assert receipt["workload"]["sql_business_request_success_count"] == 1
    assert receipt["workload"]["profile_hash"] == final["profile_hash"]
    assert "never-in-public-receipt" not in json.dumps(receipt)
    assert any(name.endswith("/manifest.final.json") for name in blob_store.downloads)


def test_partial_failure_no_completion_and_explicit_receipt(workdir, blob_store, monkeypatch):
    run = raw_run(workdir)
    original = storage._upload_one

    def fail_second(service, settings, name, data, size, digest, content_type):
        if name.endswith("/requests.jsonl"):
            raise OSError("failed")
        original(service, settings, name, data, size, digest, content_type)

    monkeypatch.setattr(storage, "_upload_one", fail_second)
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticevidence")
    with pytest.raises(RuntimeError, match="Private evidence upload failed"):
        storage.archive_if_configured(run)
    assert not any(name.endswith("/archive-manifest.json") for name in blob_store.blobs)
    assert read_json(run / storage.RECEIPT)["complete_snapshot_confirmed"] is False
    assert read_json(run / storage.RECEIPT)["status"] == "private-evidence-persistence-failed"


def test_existing_blob_mismatch_is_not_overwritten(workdir, blob_store):
    run = raw_run(workdir)
    settings = storage.StorageSettings("syntheticevidence")
    receipt = storage.upload(run, settings)
    name = receipt["blob_prefix"] + "/requests.jsonl"
    blob_store.blobs[name] = (b"bad", {"sha256": "bad"})
    with pytest.raises(RuntimeError, match="immutable snapshot"):
        storage.upload(run, settings)


def test_configuration_only_uses_operator_cli_and_no_configuration_is_noop(workdir, monkeypatch):
    monkeypatch.delenv("EVIDENCE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("EVIDENCE_STORAGE_CONTAINER", raising=False)
    assert storage.configured_storage() is None
    storage.archive_if_configured(workdir)
    config = workdir / "deployment.json"
    write_json(config, {"evidence_storage_account": "syntheticevidence"})
    assert storage.configured_storage(config).credential == "azure-cli"
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticrunner")
    assert storage.configured_storage(config).credential == "managed-identity"


@pytest.mark.parametrize("account", ["https://example.invalid", "account?sig=value", "../account"])
def test_storage_endpoint_cannot_be_overridden(account):
    with pytest.raises(ValueError):
        storage.StorageSettings(account)


def test_download_verifies_every_artifact_and_preserves_private_status(workdir, blob_store):
    run = raw_run(workdir)
    (run / "locust.log").write_bytes(b"")
    settings = storage.StorageSettings("syntheticevidence")
    receipt = storage.upload(run, settings)
    target = workdir / "retrieved"
    storage.download(target, settings, receipt["blob_prefix"], receipt["manifest_sha256"])
    assert (target / "requests.jsonl").read_bytes() == (run / "requests.jsonl").read_bytes()
    assert (target / storage.MANIFEST).is_file()
    assert not (target / "shareable.zip").exists()
    assert (target / "locust.log").stat().st_size == 0
    verified = read_json(target / storage.DOWNLOAD_RECEIPT)
    assert verified["status"] == "downloaded-and-verified"
    assert verified["artifacts"] == receipt["artifacts"]
    assert verified["manifest_sha256"] == receipt["manifest_sha256"]
    assert storage.upload(target, settings)["manifest_sha256"] == receipt["manifest_sha256"]


def test_upload_and_download_use_real_sdk_range_validation(workdir, blob_store, monkeypatch):
    from azure.storage.blob import _blob_client

    run = raw_run(workdir)
    settings = storage.StorageSettings("syntheticevidence")
    service = blob_store.factory.return_value
    original = service.get_blob_client.side_effect
    checked = []

    def get_blob(container=None, blob=None):
        client = original(container, blob)
        mocked_download = client.download_blob.side_effect

        def download(**kwargs):
            result = mocked_download(**kwargs)
            with monkeypatch.context() as context:
                downloader = MagicMock(return_value=result)
                context.setattr(_blob_client, "StorageStreamDownloader", downloader)
                with BlobClient("https://example.invalid", container, blob) as sdk:
                    response = sdk.download_blob(**kwargs)
                downloader.assert_called_once()
                assert downloader.call_args.kwargs["start_range"] == 0
                assert downloader.call_args.kwargs["end_range"] == kwargs["length"] - 1
                checked.append(blob)
                return response

        client.download_blob.side_effect = download
        return client

    service.get_blob_client.side_effect = get_blob
    receipt = storage.upload(run, settings)
    storage.download(
        workdir / "sdk-retrieved", settings, receipt["blob_prefix"], receipt["manifest_sha256"]
    )
    assert len(checked) == 2 * (receipt["artifact_count"] + 1)


def test_operator_cli_refuses_private_download_outside_ignored_results(workdir, monkeypatch):
    monkeypatch.setattr(
        storage,
        "configured_storage",
        lambda *a: storage.StorageSettings("syntheticevidence", credential="azure-cli"),
    )
    with pytest.raises(SystemExit) as failure:
        storage.main(
            [
                "--run-id",
                "run-20260925T060000Z-" + "a" * 12,
                "--manifest-sha256",
                "b" * 64,
                "--output",
                str(workdir / "not-raw-results"),
            ]
        )
    assert failure.value.code != 0
    assert not (workdir / "not-raw-results").exists()


def test_download_tamper_fails_and_cleans_partial_directory(workdir, blob_store):
    run = raw_run(workdir)
    settings = storage.StorageSettings("syntheticevidence")
    receipt = storage.upload(run, settings)
    name = receipt["blob_prefix"] + "/requests.jsonl"
    blob_store.blobs[name] = (b"corrupted", {})
    target = workdir / "retrieved"
    with pytest.raises(ValueError, match="verification"):
        storage.download(target, settings, receipt["blob_prefix"], receipt["manifest_sha256"])
    assert not target.exists()


def test_download_rejects_paths_before_creating_files(workdir, blob_store):
    settings = storage.StorageSettings("syntheticevidence")
    manifest = {
        "classification": "private-raw-evidence",
        "artifact_count": 1,
        "total_bytes": 1,
        "artifacts": [{"path": "../escape", "bytes": 1, "sha256": "a" * 64}],
    }
    encoded = json.dumps(manifest).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    prefix = "runs/bundle-" + "a" * 20 + "/" + digest[:16]
    blob_store.blobs[prefix + "/" + storage.MANIFEST] = (encoded, {})
    with pytest.raises(ValueError, match="unsafe artifact"):
        storage.download(workdir / "retrieved", settings, prefix, digest)
    assert not (workdir / "retrieved").exists()


def test_download_cli_accepts_run_id_and_output_alias(workdir, blob_store, monkeypatch):
    settings = storage.StorageSettings("syntheticevidence")
    receipt = storage.upload(raw_run(workdir), settings)
    monkeypatch.setattr(storage, "configured_storage", lambda _config: settings)
    monkeypatch.setattr(storage, "ROOT", workdir)
    target = workdir / "results" / "local-untracked-runs" / "retrieved"
    assert (
        storage.main(
            [
                "--run-id",
                receipt["blob_prefix"].split("/")[1],
                "--output",
                str(target),
                "--manifest-sha256",
                receipt["manifest_sha256"],
                "--credential",
                "azure-cli",
            ]
        )
        == 0
    )
    assert (target / "requests.jsonl").is_file()


def test_cloud_job_without_destination_is_not_silent_success(workdir, monkeypatch, capsys):
    monkeypatch.setenv("CONTAINER_APP_JOB_NAME", "synthetic")
    with pytest.raises(RuntimeError, match="Private evidence upload failed"):
        storage.archive_if_configured(workdir)
    assert "private-evidence-persistence-failed" in capsys.readouterr().out
    assert read_json(workdir / storage.RECEIPT)["complete_snapshot_confirmed"] is False
