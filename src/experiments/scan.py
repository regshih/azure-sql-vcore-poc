from __future__ import annotations

import argparse
import ast
import hashlib
import io
import ipaddress
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.experiments.common import ROOT, read_json, safe_main

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".copilot",
    ".copilot-azure",
    ".azure",
    "node_modules",
}
PLACEHOLDER = re.compile(
    r"^(?:|null|none|TBD|REPLACE_ME|CHANGEME|<[^>]+>|\$\{[^}]+\}|\$[A-Za-z_]\w*"
    r"|\$\{\{.*\}\}|\{\{[^}]+\}\}|[0-]+|example(?:[.-].*)?)$",
    re.IGNORECASE,
)
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "client_secret",
    "clientsecret",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "connection_string",
    "connectionstring",
    "accountkey",
    "sharedaccesssignature",
    "private_key",
    "subscription_id",
    "subscriptionid",
    "tenant_id",
    "tenantid",
    "object_id",
    "objectid",
    "resource_group",
    "resourcegroup",
    "sql_server",
    "server_name",
    "database_name",
    "customer_name",
    "username",
    "user_name",
}
GUID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.IGNORECASE)
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "connection-string": re.compile(
        r"\b(?:Server|Data Source|AccountKey|SharedAccessSignature)\s*=\s*"
        r"(?![<${])[A-Za-z0-9][^\r\n;]*",
        re.IGNORECASE,
    ),
    "bearer-token": re.compile(r"\bBearer\s+[A-Za-z0-9_.~+/=-]{16,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})"),
    "resource-id": re.compile(
        r"/subscriptions/(?![<${])[A-Za-z0-9-]+/resourceGroups/[A-Za-z0-9_.()-]+",
        re.IGNORECASE,
    ),
    "deployment-fqdn": re.compile(
        r"\b(?!example[.-]|placeholder[.-]|your[.-]|privatelink\.)[a-z0-9-]+\."
        r"(?:database\.windows\.net|redis\.cache\.windows\.net|"
        r"[a-z0-9.-]*azurecontainerapps\.io|vault\.azure\.net)\b",
        re.IGNORECASE,
    ),
    "personal-path": re.compile(
        r"(?:[A-Za-z]:[\\/]+Users[\\/]+(?!<|example\b|USER\b)[^\\/\s\"']+|"
        r"/(?:home|Users)/(?!<|example\b|USER\b)[^/\s\"']+)",
        re.IGNORECASE,
    ),
    "sas-token": re.compile(r"[?&](?:sig|sv|se|sp)=[^&\s\"']{8,}", re.IGNORECASE),
}
# These are published built-in role definitions, never deployment identity IDs.
ROLE_GUIDS = {
    "acdd72a7-3385-48ef-bd42-f606fba81ae7",
    "b24988ac-6180-42a0-ab88-20f7382dd24c",
    "7f951dda-4ed3-4680-a7ca-43fe172d538d",
    "4633458b-17de-408a-b874-0445c86b69e6",
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
    "73c42c96-874c-492b-b04d-ab87d138a893",
}
ROLE_PATHS = ("infra/bicep/", "infra/modules/", "src/experiments/scan.py")


@dataclass(frozen=True)
class Finding:
    area: str
    source: str
    rule: str

    def public(self) -> dict[str, str]:
        return {
            "area": self.area,
            "rule": self.rule,
            "source_hash": hashlib.sha256(self.source.encode()).hexdigest()[:16],
        }


def sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or any(
        normalized.endswith("_" + suffix)
        for suffix in ("password", "token", "secret", "connection_string")
    )


def populated(value: Any) -> bool:
    return value is not None and not (
        isinstance(value, str) and bool(PLACEHOLDER.fullmatch(value.strip()))
    )


def object_findings(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if sensitive_key(str(key)) and populated(item):
                result.append("sensitive-field")
            result.extend(object_findings(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(object_findings(item))
    return result


def scan_text(text: str, source: str, names: list[str] | None = None) -> list[str]:
    rules = [
        key
        for key, regex in PATTERNS.items()
        if regex.search(text)
        and (
            key != "connection-string"
            or not source.endswith(".py")
            or re.search(
                r"\b(?:Server|Data Source)\s*=\s*(?:tcp:)?"
                r"(?![${<])[a-z0-9][a-z0-9.-]+[,;]"
                r"|\b(?:AccountKey|SharedAccessSignature)=[A-Za-z0-9+/]{8,}",
                text,
                re.I,
            )
        )
    ]
    normalized_path = source.replace("\\", "/")
    policy_path = normalized_path.split(".whl:", 1)[-1]
    if policy_path.startswith("build/lib/"):
        policy_path = policy_path[len("build/lib/") :]
    for match in GUID.finditer(text):
        if not (
            match.group().lower() in ROLE_GUIDS and policy_path.startswith(ROLE_PATHS)
        ) and not PLACEHOLDER.fullmatch(match.group()):
            rules.append("azure-identifier")
            break
    for match in re.finditer(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if not address.is_loopback and not address.is_unspecified:
            prefix = text[max(0, match.start() - 40) : match.start()]
            if re.search(r"""["'](?:contentVersion|application_version)["']\s*:\s*["']$""", prefix):
                continue
            documentation_ip = any(
                address in ipaddress.ip_network(network)
                for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
            )
            if documentation_ip and (
                policy_path.startswith(("tests/", "docs/"))
                or policy_path == "src/experiments/scan.py"
            ):
                continue
            suffix = text[match.end() : match.end() + 4]
            cidr = re.match(r"/\d{1,2}\b", suffix)
            if cidr and policy_path.startswith(("infra/", "src/configuration/")):
                try:
                    ipaddress.ip_network(match.group() + cidr.group(), strict=True)
                    continue
                except ValueError:
                    pass
            rules.append("ip-address")
            break
    for candidate in re.findall(
        r"(?<![\w:])(?:[a-fA-F0-9]{0,4}:){2,}[a-fA-F0-9]{0,4}(?![\w:.%-])",
        text,
    ):
        try:
            ipv6 = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not ipv6.is_loopback and not ipv6.is_unspecified:
            rules.append("ip-address")
            break
    if names and any(name and name.casefold() in text.casefold() for name in names):
        rules.append("customer-redaction")
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        value = None
    if value is not None:
        rules.extend(object_findings(value))
    if source.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return sorted(set(rules))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    if any(
                        isinstance(target, ast.Name) and sensitive_key(target.id)
                        for target in targets
                    ) and populated(node.value.value):
                        rules.append("sensitive-assignment")
        return sorted(set(rules))
    # Nonliteral template expressions do not contain deployed values.
    for line in text.splitlines():
        assignment = re.match(r"^\s*(?:export\s+)?([A-Za-z_][\w-]*)\s*[:=]\s*(.+)$", line)
        if assignment and sensitive_key(assignment[1]):
            raw = assignment[2].strip().strip("'\"")
            if (
                policy_path.startswith(".github/workflows/")
                and assignment[1] == "id-token"
                and raw in {"write", "read", "none"}
            ):
                continue
            if source.endswith(".bicep") and assignment[2].strip()[:1] not in {"'", '"'}:
                continue
            if populated(raw) and not raw.startswith(
                ("#", "Field(", "os.", "settings.", "SecretStr(")
            ):
                rules.append("sensitive-assignment")
    return sorted(set(rules))


def scan_bytes(
    data: bytes,
    source: str,
    area: str,
    names: list[str],
) -> list[Finding]:
    filename = Path(source.split(":")[-1]).name
    if filename == ".env" and data.strip():
        return [Finding(area, source, "populated-environment-file")]
    if filename.endswith((".pfx", ".p12", ".bak", ".bacpac", ".tfstate")):
        return [Finding(area, source, "prohibited-public-artifact")]
    if data.startswith(b"PK\x03\x04"):
        result: list[Finding] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if (
                len(archive.infolist()) > 10000
                or sum(item.file_size for item in archive.infolist()) > 200_000_000
            ):
                return [Finding(area, source, "oversized-archive-not-scanned")]
            for item in archive.infolist():
                if item.file_size > 50_000_000:
                    result.append(Finding(area, source, "oversized-archive-entry"))
                    continue
                result.extend(
                    scan_bytes(
                        archive.read(item),
                        source + ":" + item.filename,
                        area,
                        names,
                    )
                )
        return result
    return [
        Finding(area, source, rule)
        for rule in scan_text(data.decode("utf-8", errors="replace"), source, names)
    ]


def scan_directory(root: Path, names: list[str] | None = None) -> list[Finding]:
    result: list[Finding] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.is_symlink():
            result.append(Finding("worktree", str(relative), "symlink-not-scanned"))
        elif path.is_file():
            if path.stat().st_size > 50_000_000:
                result.append(Finding("worktree", str(relative), "oversized-file-not-scanned"))
                continue
            result.extend(
                scan_bytes(path.read_bytes(), relative.as_posix(), "worktree", names or [])
            )
    return result


def git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"Git scan command failed (exit {completed.returncode})")
    return completed.stdout


def scan_git(root: Path, names: list[str] | None = None) -> list[Finding]:
    resolved_root = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if resolved_root != root.resolve():
        raise ValueError("Refusing to scan a parent repository outside the explicit project root")
    result: list[Finding] = []
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        object_id = metadata.split()[1].decode()
        source = filename.decode("utf-8", errors="replace")
        result.extend(
            scan_bytes(git(root, "cat-file", "blob", object_id), source, "staged", names or [])
        )
    objects = git(root, "rev-list", "--objects", "--all").decode().splitlines()
    for entry_text in objects:
        object_id, _, source = entry_text.partition(" ")
        kind = git(root, "cat-file", "-t", object_id).decode().strip()
        if kind == "blob":
            result.extend(
                scan_bytes(
                    git(root, "cat-file", "blob", object_id),
                    source or object_id,
                    "history",
                    names or [],
                )
            )
        elif kind == "tag":
            result.extend(
                scan_bytes(
                    git(root, "cat-file", "tag", object_id),
                    object_id,
                    "history-tag",
                    names or [],
                )
            )
        elif kind == "commit":
            commit = git(root, "cat-file", "commit", object_id).decode("utf-8", errors="replace")
            header, _, message = commit.partition("\n\n")
            result.extend(
                Finding("history-message", object_id, rule)
                for rule in scan_text(message, object_id, names)
            )
            for line in header.splitlines():
                if line.startswith(("author ", "committer ")):
                    address = re.search(r"<([^>]+)>", line)
                    if not address or not address[1].endswith("@users.noreply.github.com"):
                        result.append(
                            Finding("history-identity", object_id, "personal-git-identity")
                        )
    return result


def gitleaks(root: Path) -> tuple[list[Finding], str]:
    executable = shutil.which("gitleaks")
    if not executable:
        return [], "not installed; custom scan executed, gitleaks not executed"
    findings: list[Finding] = []
    modes = ["dir", "git"] if (root / ".git").exists() else ["dir"]
    for mode in modes:
        result = subprocess.run(
            [executable, mode, str(root), "--no-banner", "--redact", "--exit-code", "1"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 1:
            findings.append(Finding("gitleaks", mode, "secret-scanner-finding"))
        elif result.returncode:
            raise RuntimeError(f"Gitleaks execution failed (exit {result.returncode})")
    return findings, "executed"


def scan(
    root: Path,
    *,
    names: list[str] | None = None,
    include_git: bool = True,
    use_gitleaks: bool = True,
) -> dict[str, Any]:
    findings = scan_directory(root, names)
    if include_git:
        findings.extend(scan_git(root, names))
    status = "not requested"
    if use_gitleaks:
        extra, status = gitleaks(root)
        findings.extend(extra)
    return {
        "passed": not findings,
        "finding_count": len(findings),
        "findings": [finding.public() for finding in findings],
        "gitleaks": status,
        "git_history_scanned": include_git,
        "ignored_results_scanned": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan worktree, ignored evidence, index and history"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--redactions", type=Path, help="Local JSON array of customer-specific strings"
    )
    parser.add_argument("--no-git", action="store_true", help="Evidence directory only")
    args = parser.parse_args(argv)
    names = read_json(args.redactions) if args.redactions else []
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("Redactions must be a JSON list of strings")
    report = scan(args.root.resolve(), names=names, include_git=not args.no_git)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
