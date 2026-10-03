"""Entry point: `replay-helper` / `python -m replay_helper`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .dcs import protocol
from .dcs.link import DcsLink
from .dcs.speed import AutoKeyBackend, SpeedController
from .seek import SeekController
from .ui.main_window import MainWindow


def main() -> int:
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
    window = MainWindow(link, speed, seek)
    window.show()
    acmi = [arg for arg in sys.argv[1:] if arg.lower().endswith(".acmi")]
    if acmi:
        window.load_acmi(acmi[0])  # replay-helper path/to/recording.zip.acmi
    code = app.exec()
    speed.shutdown()
    link.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
