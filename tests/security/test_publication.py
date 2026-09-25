import json
import subprocess
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from src.experiments.client import guard_unsafe, origin
from src.experiments.common import read_json, write_json
from src.experiments.evidence import initialize
from src.experiments.profiles import load_profile
from src.experiments.sanitize import sanitize, sanitize_document
from src.experiments.scan import scan, scan_bytes, scan_directory, scan_git, scan_text


@pytest.mark.parametrize(
    "host",
    [
        "https://user:private@example.invalid",
        "https://example.invalid/path",
        "https://example.invalid?sig=private",
        "file:///local",
    ],
)
def test_targets_cannot_contain_credentials_or_paths(host):
    with pytest.raises(ValueError):
        origin(host)


def test_unsafe_requires_both_flags_metadata_and_exact_origin(monkeypatch):
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", "synthetic-runtime-value")
    profile = load_profile("connection-storm")
    for allow, confirm in ((False, True), (True, False), (False, False)):
        with pytest.raises(ValueError):
            guard_unsafe("http://localhost", profile, allow, confirm, [], {"poc": True})
    with pytest.raises(ValueError):
        guard_unsafe("http://localhost", profile, True, True, [], {"poc": False})
    with pytest.raises(ValueError):
        guard_unsafe("https://production.invalid", profile, True, True, [], {"poc": True})
    with pytest.raises(ValueError):
        guard_unsafe(
            "http://production.invalid",
            profile,
            True,
            True,
            ["http://production.invalid"],
            {"poc": True},
        )
    guard_unsafe(
        "https://evaluation.invalid",
        profile,
        True,
        True,
        ["https://evaluation.invalid"],
        {
            "poc_mode": True,
            "poc_marker": "sql-vcore",
            "environment": "poc",
            "application": "synthetic-azure-sql-vcore-poc",
            "synthetic_data_only": True,
        },
    )


@pytest.mark.parametrize(
    "override", [{"poc_mode": False}, {"poc_marker": None}, {"environment": "production"}]
)
def test_unsafe_rejects_disabled_or_non_poc_modes_even_when_application_name_matches(
    monkeypatch, override
):
    monkeypatch.setenv("POC_INTERNAL_API_TOKEN", "synthetic-runtime-value")
    metadata = {
        "poc_mode": True,
        "poc_marker": "sql-vcore",
        "environment": "poc",
        "application": "synthetic-azure-sql-vcore-poc",
        "synthetic_data_only": True,
        **override,
    }
    with pytest.raises(ValueError, match="POC marker"):
        guard_unsafe("http://localhost", load_profile("connection-storm"), True, True, [], metadata)


def test_sanitizer_drops_nested_names_arrays_multiline_urls_sql_and_headers(workdir):
    raw = workdir / "raw"
    initialize(raw)
    sensitive = str(uuid4())
    hostile = {
        "test_run_id": sensitive,
        "correlation_id": sensitive,
        "request_count": 15,
        "failed_operations": [
            {
                "correlation_id": sensitive,
                "elapsed_ms": 12,
                "operation": "CustomerName\nhttps://private.invalid/path?key=opaque",
                "headers": {"Authorization": "not-for-publication"},
                "raw_sql": "select customer_records",
                "error_code": "CustomerName",
                "unrecognized": ["CustomerName", {"nested": sensitive}],
            }
        ],
        "CustomerName": {"value": sensitive},
        "value": ["CustomerName", sensitive, 0],
    }
    write_json(raw / "workload-summary.json", hostile)
    (raw / "observations.md").write_text("# CustomerName\n" + sensitive)
    archive = sanitize(raw, workdir / "shareable", redactions=["CustomerName"])
    assert archive.exists()
    with zipfile.ZipFile(archive) as bundle:
        content = b"\n".join(bundle.read(name) for name in bundle.namelist()).decode()
    assert "CustomerName" not in content
    assert sensitive not in content
    assert "Authorization" not in content
    assert "customer_records" not in content
    result = read_json(workdir / "shareable" / "workload-summary.json")
    assert result["request_count"] == 15
    assert result["test_run_id"] == result["correlation_id"]
    assert result["correlation_id"] == result["failed_operations"][0]["correlation_id"]
    assert result["value"][-1] == 0
    assert not scan_directory(workdir / "shareable", ["CustomerName"])


def test_sanitizer_requires_review_and_never_packages_incomplete_input(workdir):
    raw = workdir / "raw"
    initialize(raw)
    with pytest.raises(ValueError, match="redaction list"):
        sanitize(raw, workdir / "shareable")
    (raw / "manifest.json").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        sanitize(raw, workdir / "shareable", confirm_no_customer_data=True)
    assert not (workdir / "shareable.zip").exists()


def test_sanitization_schema_rejects_unknown_artifacts():
    with pytest.raises(ValueError):
        sanitize_document("raw-headers.json", {})


def test_scanner_finds_nested_secret_keys_and_multiline_values():
    content = json.dumps({"nested": [{"client_secret": "synthetic\nsensitive"}]})
    assert "sensitive-field" in scan_text(content, "config.json")
    assert "azure-identifier" in scan_text(str(uuid4()), "results/run.json")
    assert "customer-redaction" in scan_text("a customer-name b", "note.md", ["customer-name"])
    env = "API_" + "TOKEN=synthetic-populated-value"
    assert "sensitive-assignment" in scan_text(env, ".env")
    assert not scan_text("API_" + "TOKEN=<placeholder>", ".env.example")


def git(root: Path, *args: str):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    return result.stdout


def test_scanner_checks_ignored_worktree_staged_and_deleted_history(workdir):
    repo = workdir / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "POC Test")
    git(repo, "config", "user.email", "poc-test@users.noreply.github.com")
    secret = str(uuid4())
    tracked = repo / "tracked.txt"
    tracked.write_text(secret)
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "--quiet", "-m", "Synthetic history fixture")
    tracked.unlink()
    git(repo, "add", "-u")
    git(repo, "commit", "--quiet", "-m", "Remove fixture")
    staged = repo / "staged.txt"
    staged.write_text(secret)
    git(repo, "add", "staged.txt")
    staged.write_text("clean worktree")
    (repo / ".gitignore").write_text("results/\n")
    ignored = repo / "results" / "local-untracked-runs"
    ignored.mkdir(parents=True)
    (ignored / "evidence.json").write_text(json.dumps({"value": secret}))
    report = scan(repo, use_gitleaks=False)
    areas = {item["area"] for item in report["findings"]}
    assert {"worktree", "staged", "history"} <= areas
    assert secret not in json.dumps(report)
    assert report["passed"] is False


def test_scanner_reads_commit_messages_and_rejects_personal_identity(workdir):
    repo = workdir / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Synthetic Author")
    git(repo, "config", "user.email", "synthetic-author@example.invalid")
    (repo / "clean").write_text("nothing sensitive")
    git(repo, "add", "clean")
    git(repo, "commit", "--quiet", "-m", "Synthetic marker " + str(uuid4()))
    findings = scan_git(repo)
    assert any(item.area == "history-message" for item in findings)
    assert any(item.area == "history-identity" for item in findings)


def test_allowlist_for_public_role_ids_is_path_scoped():
    from src.experiments.scan import ROLE_GUIDS

    for role in ROLE_GUIDS:
        assert not scan_text(role, "infra/bicep/modules/identity.bicep")
        assert "azure-identifier" in scan_text(role, "results/raw.json")


def test_ipv6_and_ipv4_are_detected_without_github_command_false_positives():
    private_v4 = ".".join(["10", "20", "30", "40"])
    private_v6 = ":".join(["fd12", "3456", "", "abcd"])
    assert "ip-address" in scan_text(private_v4, "raw.json")
    assert "ip-address" in scan_text(private_v6, "raw.json")
    assert "ip-address" not in scan_text("echo ::error::deployment failed", "workflow.yml")
    assert not scan_text(
        'echo "::add-mask::${!key}"\nid-token: write',
        ".github/workflows/deploy.yml",
    )
    assert "ip-address" not in scan_text('{"contentVersion":"1.0.0.0"}', "template.json")


def test_populated_env_and_database_backups_fail_closed():
    assert scan_bytes(b"APP_MODE=local", ".env", "worktree", [])[0].rule == (
        "populated-environment-file"
    )
    assert scan_bytes(b"opaque binary", "database.bacpac", "history", [])[0].rule == (
        "prohibited-public-artifact"
    )
