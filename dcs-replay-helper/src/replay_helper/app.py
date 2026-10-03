"""Entry point: `replay-helper` / `python -m replay_helper`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .dcs import protocol
from .dcs.link import DcsLink
from .dcs.speed import AutoKeyBackend, SpeedController
from .seek import SeekController
from .settings import Settings
from .ui.main_window import MainWindow


def main() -> int:
    if "--version" in sys.argv[1:]:
        from . import __version__, hook_installer

        print(f"DCS Replay Helper {__version__} (hook {hook_installer.hook_version(hook_installer.bundled_hook())})")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("DCS Replay Helper")
    link = DcsLink()
    if not link.start():
        QMessageBox.critical(
            None,
            "DCS Replay Helper",
            f"Cannot listen on {protocol.HOST}:{protocol.STATE_PORT} ({link.bind_error()}).\n\n"
            "Is another copy of the Replay Helper, or the spike client, still running?",
        )
        return 1
    speed = SpeedController(link, AutoKeyBackend(link))
    seek = SeekController(link, speed)
    window = MainWindow(link, speed, seek, Settings())
    window.show()
    window.check_hook()
    # replay-helper [recording.zip.acmi] [track.trk]
    for arg in sys.argv[1:]:
        if arg.lower().endswith(".acmi"):
            window.load_acmi(arg)
        elif arg.lower().endswith(".trk"):
            window.events.load_track(arg)
    code = app.exec()
    speed.shutdown()
    link.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
