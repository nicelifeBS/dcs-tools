"""Main window. Milestone 1: connection, clock, play/pause and a manual stop."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..dcs.link import DcsLink
from ..dcs.protocol import Armed, Arrived, Disarmed, Error, Hello, Message, Pong, State
from ..timefmt import fmt_model, fmt_speed, fmt_tod

REFRESH_MS = 50


class MainWindow(QMainWindow):
    def __init__(self, link: DcsLink) -> None:
        super().__init__()
        self.link = link
        self.setWindowTitle("DCS Replay Helper")

        # connection
        self.conn_label = QLabel()
        self.mission_label = QLabel()
        self.mission_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        top = QHBoxLayout()
        top.addWidget(self.conn_label)
        top.addStretch(1)
        top.addWidget(self.mission_label)

        # clock
        self.clock_label = QLabel()
        big = QFont()
        big.setPointSize(28)
        big.setBold(True)
        big.setStyleHint(QFont.StyleHint.Monospace)
        self.clock_label.setFont(big)
        self.tod_label = QLabel()
        self.speed_label = QLabel()
        clock_box = QVBoxLayout()
        clock_box.addWidget(self.clock_label)
        clock_box.addWidget(self.tod_label)
        clock_box.addWidget(self.speed_label)

        # transport
        self.play_button = QPushButton()
        self.play_button.setMinimumHeight(40)
        self.play_button.clicked.connect(self._toggle_play)

        # manual stop
        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setRange(0.0, 24 * 3600.0)
        self.stop_spin.setDecimals(2)
        self.stop_spin.setSuffix(" s")
        self.arm_button = QPushButton("Arm stop")
        self.arm_button.clicked.connect(lambda: self.link.arm_stop(self.stop_spin.value()))
        self.disarm_button = QPushButton("Disarm")
        self.disarm_button.clicked.connect(self.link.disarm)
        self.stop_label = QLabel()
        stop_row = QHBoxLayout()
        stop_row.addWidget(QLabel("Pause at model time"))
        stop_row.addWidget(self.stop_spin)
        stop_row.addWidget(self.arm_button)
        stop_row.addWidget(self.disarm_button)
        stop_box = QGroupBox("Stop")
        stop_layout = QVBoxLayout(stop_box)
        stop_layout.addLayout(stop_row)
        stop_layout.addWidget(self.stop_label)

        # log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)

        root = QVBoxLayout()
        root.addLayout(top)
        root.addLayout(clock_box)
        root.addWidget(self.play_button)
        root.addWidget(stop_box)
        root.addWidget(self.log_view, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(520, 480)

        link.connectedChanged.connect(self._on_connected)
        link.stateChanged.connect(self._on_state)
        link.message.connect(self._on_message)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._on_connected(link.connected)
        self.refresh()

    # --- actions ----------------------------------------------------------------------
    def _toggle_play(self) -> None:
        s = self.link.state
        if s is None:
            return
        if s.paused:
            self.link.resume()
        else:
            self.link.pause()

    def _set_play_button(self, paused: bool) -> None:
        # Standard icons instead of ▶/⏸ characters, which some fonts lack.
        icon = QStyle.StandardPixmap.SP_MediaPlay if paused else QStyle.StandardPixmap.SP_MediaPause
        self.play_button.setIcon(self.style().standardIcon(icon))
        self.play_button.setText("Play" if paused else "Pause")

    # --- link events ------------------------------------------------------------------
    def _on_connected(self, connected: bool) -> None:
        if connected:
            version = self.link.hook_version or "?"
            self.conn_label.setText(f"● Connected to DCS (hook {version})")
            self.conn_label.setStyleSheet("color: #2e7d32;")
        else:
            self.conn_label.setText("○ Waiting for DCS: start a track replay with the hook installed")
            self.conn_label.setStyleSheet("color: #9e9e9e;")
        for w in (self.play_button, self.arm_button, self.disarm_button):
            w.setEnabled(connected)

    def _on_state(self, s: State) -> None:
        parts = [p for p in (s.theatre, s.date) if p]
        if not s.track:
            parts.append("(not a track replay)")
        self.mission_label.setText("  ".join(parts))
        self._set_play_button(s.paused)
        if s.stop is not None:
            self.stop_label.setText(f"Armed: pauses at {fmt_model(s.stop)} ({s.stop:.2f} s)")

    def _on_message(self, msg: Message) -> None:
        if isinstance(msg, Arrived):
            self.stop_label.setText(f"Stopped at {fmt_model(msg.t)} ({msg.over:.3f} s after the target)")
            self._log(f"arrived t={msg.t:.3f} target={msg.target:.3f} over={msg.over:.3f}")
        elif isinstance(msg, Armed):
            self._log(f"armed stop at {msg.target:.3f} (now {msg.now:.3f})")
        elif isinstance(msg, Disarmed):
            self.stop_label.setText("")
            self._log(f"stop disarmed ({msg.reason})")
        elif isinstance(msg, Error):
            self._log(f"DCS: {msg.text}")
        elif isinstance(msg, (Hello, Pong)):
            self._on_connected(self.link.connected)
            if isinstance(msg, Hello):
                self._log(f"hook {msg.version} connected")

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    # --- periodic ---------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.link.state
        t = self.link.model_time_now() if self.link.connected else None
        self.clock_label.setText(fmt_model(t))
        if s is None or not self.link.connected:
            self.tod_label.setText("Mission time --:--:--")
            self.speed_label.setText("")
            self._set_play_button(True)
            return
        tod = None if s.start_tod is None or t is None else s.start_tod + t
        self.tod_label.setText(f"Mission time {fmt_tod(tod)}")
        if s.paused:
            self.speed_label.setText(f"Paused (speed set to {fmt_speed(s.accel)})")
        else:
            measured = f", measured {fmt_speed(s.speed)}" if s.speed is not None else ""
            self.speed_label.setText(f"Speed {fmt_speed(s.accel)}{measured}")
        if s.stop is None and not self.stop_label.text().startswith("Stopped"):
            self.stop_label.setText("")
