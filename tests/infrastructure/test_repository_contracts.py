from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import get_args
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
import yaml

from src.configuration.settings import Settings
from src.operations.validate import ROOT, migration_errors


@pytest.fixture
def scratch() -> Iterator[Path]:
    directory = ROOT / "build" / "validation-tests" / uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def test_migrations_are_nonempty_contiguous_and_uniquely_numbered() -> None:
    assert migration_errors(ROOT / "sql" / "migrations") == []


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["0002_first.sql"],
        ["0001_first.sql", "0003_gap.sql"],
        ["0001_first.sql", "0001_duplicate.sql"],
        ["1_invalid.sql"],
    ],
)
def test_migration_validator_rejects_invalid_sequences(scratch: Path, names: list[str]) -> None:
    for name in names:
        (scratch / name).write_text("SELECT 1;\n", encoding="utf-8")
    assert migration_errors(scratch)


def test_migration_validator_accepts_sequence_and_rejects_empty_file(scratch: Path) -> None:
    for name in ("0001_initial.sql", "0002_next.sql"):
        (scratch / name).write_text("SELECT 1;\n", encoding="utf-8")
    assert migration_errors(scratch) == []
    (scratch / "0002_next.sql").write_text("", encoding="utf-8")
    assert any("Empty migration" in error for error in migration_errors(scratch))


def markdown_files() -> list[Path]:
    return [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / "dashboards").rglob("*.md"),
        *(ROOT / "sql").rglob("*.md"),
    ]


def test_all_relative_markdown_file_links_resolve() -> None:
    errors: list[str] = []
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        links = re.findall(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^)]*)?\)", text)
        links += re.findall(r"(?m)^\s*\[[^\]]+\]:\s*(\S+)", text)
        for link in links:
            link = link.strip("<>")
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = unquote(parsed.path).replace("\\", "/")
            resolved = ROOT / target.lstrip("/") if target.startswith("/") else path.parent / target
            if not resolved.exists():
                errors.append(f"{path.relative_to(ROOT)} -> {link}")
    assert not errors, "Broken local Markdown file links:\n" + "\n".join(errors)


def test_readme_referenced_repository_paths_exist() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    # Check individual command paths, not merely the existence of a scripts directory.
    paths = re.findall(
        r"(?<![\w/])(?:\.?[\\/])?((?:scripts|sql|infra|load-tests|dashboards|docs|tests|src)"
        r"[\\/][\w./\\*-]+\.(?:py|ps1|sh|sql|bicep|bicepparam|json|ya?ml|md))",
        text,
    )
    errors = [path for path in paths if not list(ROOT.glob(path.replace("\\", "/").rstrip(".")))]
    assert not errors, f"README references missing files: {errors}"


def readme_modules() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\s-m\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)", text)))


def test_readme_python_module_commands_resolve() -> None:
    modules = readme_modules()
    assert modules, "README must document runnable Python commands"
    for module in modules:
        assert importlib.util.find_spec(module) is not None, f"Missing README module: {module}"


@pytest.mark.parametrize("module", [m for m in readme_modules() if m.startswith("src.")])
def test_readme_project_module_help_is_safe_and_exits(module: str) -> None:
    if module == "src.api":
        launcher = (ROOT / "src" / "api" / "__main__.py").read_text(encoding="utf-8")
        assert "parse_args" in launcher, (
            "API launcher must parse --help before starting the service"
        )
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"{module} --help failed: {result.stderr}"
    assert "usage:" in result.stdout.lower(), f"{module} did not expose command syntax"


def readme_project_commands() -> list[tuple[str, str, tuple[str, ...]]]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    commands: set[tuple[str, str, tuple[str, ...]]] = set()
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL):
        block = block.replace("\\\n", " ").replace("`\n", " ")
        for module, rest in re.findall(r"\s-m\s+(src\.[\w.]+)([^\n]*)", block):
            subcommand = re.match(r"\s+([a-z][\w-]*)\b", rest)
            options = tuple(sorted(set(re.findall(r"(?<!\w)--[a-z][a-z0-9-]*", rest))))
            commands.add((module, subcommand[1] if subcommand else "", options))
    return sorted(commands)


@pytest.mark.parametrize(("module", "subcommand", "options"), readme_project_commands())
def test_readme_subcommands_and_option_names(
    module: str, subcommand: str, options: tuple[str, ...]
) -> None:
    if module == "src.api":
        return  # Its safe-launcher contract is checked above; never start the service.
    command = [sys.executable, "-m", module]
    if subcommand:
        command.append(subcommand)
    result = subprocess.run(
        [*command, "--help"], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, f"Invalid documented command: {module} {subcommand}"
    for option in options:
        assert option in result.stdout, f"Unknown README option {option}: {module} {subcommand}"


def test_documented_literal_option_values_match_declared_choices() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    cache_backends = get_args(Settings.model_fields["cache_backend"].annotation)
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL):
        block = block.replace("\\\n", " ").replace("`\n", " ")
        for module, rest in re.findall(r"\s-m\s+(src\.[\w.]+)([^\n]*)", block):
            spec = importlib.util.find_spec(module)
            assert spec is not None and spec.origin is not None, module
            source = Path(spec.origin)
            if source.name == "__init__.py":
                source = source.with_name("__main__.py")
            tree = ast.parse(source.read_text(encoding="utf-8"))
            choices: dict[str, set[str]] = {}
            for call in ast.walk(tree):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_argument"
                ):
                    continue
                for keyword in call.keywords:
                    if keyword.arg != "choices":
                        continue
                    try:
                        values = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError):
                        continue  # Dynamic choices are not inferred or executed.
                    if not isinstance(values, (tuple, list, set)):
                        continue
                    for argument in call.args:
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                            choices.setdefault(argument.value, set()).update(map(str, values))
            for option, raw_value in re.findall(r"(--[\w-]+)\s+([^\s`]+)", rest):
                value = raw_value.strip("\"'")
                if value.startswith(("-", "<", "$", "{")):
                    continue  # Never execute or guess placeholder values.
                if option == "--cache-modes":
                    assert set(value.split(",")) <= set(cache_backends), value
                elif option in choices:
                    assert value in choices[option], f"{module} {option}: invalid value {value}"


def test_shell_wrapper_parity_and_lifecycle_scripts() -> None:
    scripts = ROOT / "scripts"
    sh = {path.stem.lower(): path for path in scripts.glob("*.sh")}
    ps1 = {path.stem.lower(): path for path in scripts.glob("*.ps1")}
    assert sh.keys() == ps1.keys(), "Each shell script must have its PowerShell counterpart"
    assert {"validate", "destroy"} <= sh.keys(), "Validation and cleanup wrappers are required"
    for name in sh:
        bash = sh[name].read_text(encoding="utf-8")
        powershell = ps1[name].read_text(encoding="utf-8")
        if name == "invoke-poc":
            assert "-m src.operations.cli" in bash and '"$@"' in bash
            assert "-m $Module $Operation @Arguments" in powershell
            continue
        bash_modules = re.findall(r"-m\s+(src\.[\w.]+)", bash)
        powershell_modules = re.findall(r"-m\s+(src\.[\w.]+)", powershell)
        helper_operation = re.search(r'/invoke-poc\.sh"\s+([\w-]+)', bash)
        if helper_operation:
            bash_modules = ["src.operations.cli"]
            powershell_modules = re.findall(r"-Module\s+(src\.[\w.]+)", powershell)
            assert f"-Operation {helper_operation[1]}" in powershell, name
        assert bash_modules == powershell_modules, f"{name}: entrypoint mismatch"
        assert bash_modules, f"{name}: no verifiable Python entrypoint"
        assert '"$@"' in bash, f"{name}: Bash drops caller arguments"
        assert "@args" in powershell or "-Arguments $args" in powershell, name


def test_ci_is_offline_and_deploy_is_explicit_oidc() -> None:
    workflows = ROOT / ".github" / "workflows"
    for path in workflows.glob("*.yml"):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        assert isinstance(document, dict)
        for job in document["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses")
                if action:
                    assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), action
    ci = (workflows / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/validate.sh" in ci
    assert "fetch-depth: 0" in ci
    assert "azure/login@" not in ci
    deploy = yaml.load(
        (workflows / "deploy.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    assert set(deploy["on"]) == {"workflow_dispatch"}
    assert deploy["permissions"].get("id-token") is None
    job = deploy["jobs"]["deploy"]
    assert job["environment"] == "poc"
    assert job["permissions"]["id-token"] == "write"
    assert job["if"] == "inputs.confirm_poc"
    serialized = json.dumps(deploy)
    assert "secrets.AZURE" not in serialized
    assert "--confirm-poc" in serialized
    assert "git check-ignore --quiet deployment.local.json" in serialized


def test_dashboard_json_and_sql_documentation_contracts() -> None:
    for name in ("workbook.json", "grafana.json"):
        assert isinstance(
            json.loads((ROOT / "dashboards" / name).read_text(encoding="utf-8")), dict
        )
    for directory in ("diagnostics", "query-store", "restore-validation"):
        for path in (ROOT / "sql" / directory).glob("*.sql"):
            text = path.read_text(encoding="utf-8")
            for label in (
                "Purpose/context:",
                "Permissions:",
                "Output:",
                "Interpret:",
                "Limitations:",
            ):
                assert label in text, f"{path.name}: missing {label}"
            assert not re.search(r"(?im)^\s*(DROP|DELETE|UPDATE|ALTER|TRUNCATE|DBCC)\b", text)
