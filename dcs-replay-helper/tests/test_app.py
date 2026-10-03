import sys

from replay_helper import __version__, app


def test_version_flag(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["replay-helper", "--version"])
    assert app.main() == 0
    assert capsys.readouterr().out.strip() == f"DCS Replay Helper {__version__} (hook 0.1.0)"
