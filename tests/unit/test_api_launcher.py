import pytest

from src.api import __main__ as launcher


def test_help_exits_before_settings_or_server_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["src.api", "--help"])
    monkeypatch.setattr(
        launcher, "Settings", lambda: pytest.fail("Help must not load runtime settings.")
    )
    monkeypatch.setattr(
        launcher.uvicorn, "run", lambda *args, **kwargs: pytest.fail("Must not start server.")
    )
    with pytest.raises(SystemExit) as exit_info:
        launcher.main()
    assert exit_info.value.code == 0
    assert "environment configuration" in capsys.readouterr().out
