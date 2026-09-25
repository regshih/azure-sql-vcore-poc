from __future__ import annotations

import subprocess

import pytest

from src.operations import validate


def test_missing_tools_fail_closed_and_explicit_override_reports_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        validate, "checks", lambda: [validate.Check("Missing scanner", ("missing",), "security")]
    )
    monkeypatch.setattr(validate, "unavailable", lambda _: "not installed")
    assert validate.main(["--only", "security"]) == 1
    assert "FAIL Missing scanner: not installed" in capsys.readouterr().out
    assert validate.main(["--only", "security", "--allow-missing-tools"]) == 0
    assert "SKIP Missing scanner: not installed" in capsys.readouterr().out


def test_selected_skips_never_run_a_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        validate, "checks", lambda: [validate.Check("Scanner", ("missing",), "security")]
    )

    def unexpected(_: validate.Check) -> bool:
        pytest.fail("Explicitly excluded check executed")

    monkeypatch.setattr(validate, "run_check", unexpected)
    assert validate.main(["--only", "security", "--skip-security"]) == 0
    assert "SKIP Scanner: excluded explicitly" in capsys.readouterr().out


def test_runner_preserves_tool_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode=2),
    )
    assert not validate.run_check(validate.Check("lint", ("lint",), "python"))


def test_runner_handles_missing_executable_without_claiming_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(validate.subprocess, "run", missing)
    assert not validate.run_check(validate.Check("lint", ("lint",), "python"))


def test_import_checks_are_each_isolated_in_fresh_python_processes() -> None:
    imports = [check for check in validate.checks() if check.group == "imports"]
    assert imports
    assert any("src.api.__main__" in check.name for check in imports)
    for check in imports:
        assert check.command[:2] == (validate.sys.executable, "-c")
        assert check.command[2].count("import_module(") == 1


def test_bicep_never_writes_compiled_output_beside_source() -> None:
    check = next(check for check in validate.checks() if check.name == "Bicep build")
    output = check.command[check.command.index("--outfile") + 1]
    assert str(validate.ROOT / "build" / "validation") in output


def test_default_tests_disable_inherited_live_opt_ins() -> None:
    offline = validate.test_check(False)
    assert dict(offline.environment)["RUN_AZURE_SQL_TESTS"] == "0"
    assert dict(offline.environment)["RUN_AZURE_TESTS"] == "0"
    assert offline.command[-2:] == ("-m", "not azure and not sql")
    cloud = validate.test_check(True)
    assert cloud.command[-2:] == ("pytest", "tests")
    assert not cloud.environment, "Cloud opt-in still comes from caller's test environment"


def test_publication_scanner_has_explicit_project_scope_and_includes_git() -> None:
    check = next(check for check in validate.checks() if check.name == "Publication scanner")
    assert check.command[-2:] == ("--root", str(validate.ROOT))
    assert "--no-git" not in check.command
