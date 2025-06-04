import pytest
from server_monitor import cli


def test_cli_main_help(monkeypatch, capsys):
    # Patch sys.argv to simulate 'server-monitor --help'
    monkeypatch.setattr("sys.argv", ["server-monitor", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    out = capsys.readouterr().out
    assert "Usage" in out or "usage" in out
    assert excinfo.value.code == 0 or excinfo.value.code == 1


def test_cli_main_no_args(monkeypatch, capsys):
    # Patch sys.argv to simulate 'server-monitor' (no args)
    monkeypatch.setattr("sys.argv", ["server-monitor"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "Usage" in out or "usage" in out

# You can add more CLI argument tests as needed for your CLI implementation
