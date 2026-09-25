"""Offline quality gates. Every unavailable or deliberately skipped check is reported."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("python", "tests", "imports", "sql", "bicep", "shell", "security")


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    group: str
    environment: tuple[tuple[str, str], ...] = ()


def python_check(name: str, group: str, *args: str) -> Check:
    return Check(name, (sys.executable, "-m", *args), group)


def test_check(include_cloud: bool) -> Check:
    if include_cloud:
        return python_check("Tests including opt-in cloud tests", "tests", "pytest", "tests")
    return Check(
        "Unit and local integration tests",
        (sys.executable, "-m", "pytest", "tests", "-m", "not azure and not sql"),
        "tests",
        (("RUN_AZURE_SQL_TESTS", "0"), ("RUN_AZURE_TESTS", "0")),
    )


def migration_errors(directory: Path) -> list[str]:
    import re

    files = sorted(directory.glob("*.sql"))
    if not files:
        return ["No SQL migrations found."]
    numbers: list[int] = []
    errors: list[str] = []
    for path in files:
        match = re.fullmatch(r"(\d{4})_[a-z0-9_]+\.sql", path.name)
        if match is None:
            errors.append(f"Invalid migration filename: {path.name}")
        else:
            numbers.append(int(match.group(1)))
        if not path.read_text(encoding="utf-8").strip():
            errors.append(f"Empty migration: {path.name}")
    if numbers != list(range(1, len(files) + 1)):
        errors.append("Migrations must be unique, contiguous and start at 0001.")
    return errors


def source_modules(root: Path) -> list[str]:
    return sorted(
        ".".join(
            path.relative_to(root).parent.parts
            if path.name == "__init__.py"
            else path.relative_to(root).with_suffix("").parts
        )
        for path in (root / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def checks(root: Path = ROOT) -> list[Check]:
    result = [
        python_check("Ruff lint", "python", "ruff", "check", "src", "tests"),
        python_check("Ruff format", "python", "ruff", "format", "--check", "src", "tests"),
        python_check("Mypy", "python", "mypy", "src"),
        python_check("Wheel build", "python", "build", "--wheel", "--no-isolation"),
        test_check(False),
        python_check("T-SQL lint and parse", "sql", "sqlfluff", "lint", "sql", "--dialect", "tsql"),
        python_check("Bandit", "security", "bandit", "-q", "-r", "src", "-ll"),
        python_check(
            "Installed dependency vulnerability audit",
            "security",
            "pip_audit",
            "--progress-spinner",
            "off",
            "--skip-editable",
        ),
        Check(
            "Gitleaks working tree",
            ("gitleaks", "dir", ".", "--redact", "--config", ".gitleaks.toml"),
            "security",
        ),
        Check(
            "Gitleaks full Git history",
            ("gitleaks", "git", ".", "--redact", "--log-opts=--all", "--config", ".gitleaks.toml"),
            "security",
        ),
        python_check(
            "Publication scanner", "security", "src.experiments.scan", "--root", str(root)
        ),
    ]
    # Isolation prevents a Locust import from monkey-patching a process with existing threads.
    for module in source_modules(root):
        result.append(
            Check(
                f"Import {module}",
                (sys.executable, "-c", f"import importlib; importlib.import_module({module!r})"),
                "imports",
            )
        )
    template = root / "infra" / "bicep" / "main.bicep"
    if not template.is_file():
        template = root / "infra" / "main.bicep"
    result.extend(
        [
            Check(
                "Bicep build",
                (
                    "az",
                    "bicep",
                    "build",
                    "--file",
                    str(template),
                    "--outfile",
                    str(root / "build" / "validation" / "main.json"),
                ),
                "bicep",
            ),
            Check("Bicep lint", ("az", "bicep", "lint", "--file", str(template)), "bicep"),
        ]
    )
    bash = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            bash = str(git_bash)
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    for path in sorted((root / "scripts").glob("*.sh")):
        result.append(Check(f"Bash syntax {path.name}", (bash or "bash", "-n", str(path)), "shell"))
    for path in sorted((root / "scripts").glob("*.ps1")):
        escaped = str(path).replace("'", "''")
        code = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
            "[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) {$errors | Write-Output; exit 1}"
        )
        result.append(
            Check(
                f"PowerShell syntax {path.name}",
                (powershell or "pwsh", "-NoProfile", "-NonInteractive", "-Command", code),
                "shell",
            )
        )
    return result


def unavailable(check: Check) -> str | None:
    if not shutil.which(check.command[0]):
        return f"executable {Path(check.command[0]).name} unavailable"
    if len(check.command) > 2 and check.command[1] == "-m":
        module = check.command[2]
        try:
            if importlib.util.find_spec(module) is None:
                return f"Python module {module} unavailable (pending implementation or install)"
        except ModuleNotFoundError:
            return f"Python module {module} unavailable (pending implementation or install)"
    return None


def run_check(check: Check) -> bool:
    print(f"RUN  {check.name}", flush=True)
    try:
        executable = shutil.which(check.command[0]) or check.command[0]
        completed = subprocess.run(
            (executable, *check.command[1:]),
            cwd=ROOT,
            env=os.environ | dict(check.environment),
            check=False,
            timeout=1200,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"FAIL {check.name}: {type(error).__name__}", flush=True)
        return False
    passed = completed.returncode == 0
    print(f"{'PASS' if passed else 'FAIL'} {check.name}", flush=True)
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", choices=GROUPS)
    parser.add_argument("--skip-bicep", action="store_true")
    parser.add_argument("--skip-security", action="store_true")
    parser.add_argument("--skip-shell", action="store_true")
    parser.add_argument(
        "--include-cloud",
        action="store_true",
        help="Include cloud tests; test-specific opt-in and credentials remain required.",
    )
    parser.add_argument(
        "--allow-missing-tools",
        action="store_true",
        help="Report unavailable checks as SKIP rather than fail; not for CI.",
    )
    args = parser.parse_args(argv)
    selected = set(args.only or GROUPS)
    skipped = {group for group in ("bicep", "security", "shell") if getattr(args, f"skip_{group}")}
    failures = 0
    omissions = 0
    if "sql" in selected:
        errors = migration_errors(ROOT / "sql" / "migrations")
        for error in errors:
            print(f"FAIL SQL migration ordering: {error}")
        failures += bool(errors)
        if not errors:
            print("PASS SQL migration ordering")
    build_output = ROOT / "build" / "validation" / "main.json"
    if "bicep" in selected - skipped:
        build_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for check in checks():
            if args.include_cloud and check.group == "tests":
                check = test_check(True)
            if check.group not in selected or check.group in skipped:
                print(f"SKIP {check.name}: excluded explicitly")
                omissions += 1
                continue
            reason = unavailable(check)
            if reason is not None:
                print(f"{'SKIP' if args.allow_missing_tools else 'FAIL'} {check.name}: {reason}")
                failures += not args.allow_missing_tools
                omissions += 1
                continue
            failures += not run_check(check)
    finally:
        build_output.unlink(missing_ok=True)
    print(f"Validation finished: {failures} failure(s), {omissions} not executed.")
    if omissions:
        print("Omitted checks are NOT validated.")
    if args.include_cloud and "tests" in selected:
        print("Cloud tests included; pytest skips mean live behavior was NOT validated.")
    else:
        print("SKIP Live Azure/SQL: requires --include-cloud and test-specific opt-in.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
