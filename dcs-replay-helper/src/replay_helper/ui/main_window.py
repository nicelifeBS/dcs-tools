"""Main window: connection, clock, play/pause, speed and a manual stop."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
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
from ..dcs.keys import Step
from ..dcs.protocol import Armed, Arrived, Disarmed, Error, Hello, Message, Pong, State
from ..dcs.speed import SpeedController
from ..timefmt import fmt_model, fmt_speed, fmt_tod

REFRESH_MS = 50
SPEED_CHOICES = (0.25, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
LIMIT_CHOICES = (1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
DEFAULT_LIMIT = 4
STEP_KEYS = {Step.UP: "LCtrl+Z", Step.DOWN: "LAlt+Z", Step.NORMAL: "LShift+Z"}


class MainWindow(QMainWindow):
    def __init__(self, link: DcsLink, speed: SpeedController | None = None) -> None:
        super().__init__()
        self.link = link
        self.speed = speed
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

        # speed
        self.speed_combo = QComboBox()
        for x in SPEED_CHOICES:
            self.speed_combo.addItem(fmt_speed(x), x)
        self.speed_combo.setCurrentIndex(SPEED_CHOICES.index(1))
        self.speed_button = QPushButton("Set speed")
        self.speed_button.clicked.connect(self._set_speed)
        self.limit_combo = QComboBox()
        for x in LIMIT_CHOICES:
            self.limit_combo.addItem(fmt_speed(x), x)
        self.limit_combo.setCurrentIndex(LIMIT_CHOICES.index(DEFAULT_LIMIT))
        self.limit_combo.setToolTip("Never run the replay faster than this. If it does (for example "
                                    "after pressing the keys in DCS by hand), the replay is paused "
                                    "and brought back down to this speed.")
        self.limit_combo.currentIndexChanged.connect(self._apply_limit)
        self.speed_status = QLabel()
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed"))
        speed_row.addWidget(self.speed_combo)
        speed_row.addWidget(self.speed_button)
        speed_row.addSpacing(16)
        speed_row.addWidget(QLabel("Limit"))
        speed_row.addWidget(self.limit_combo)
        speed_row.addStretch(1)
        speed_box = QGroupBox("Speed")
        speed_layout = QVBoxLayout(speed_box)
        speed_layout.addLayout(speed_row)
        speed_layout.addWidget(self.speed_status)
        speed_box.setEnabled(speed is not None)

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
        root.addWidget(speed_box)
        root.addWidget(stop_box)
        root.addWidget(self.log_view, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(560, 560)

        link.connectedChanged.connect(self._on_connected)
        link.stateChanged.connect(self._on_state)
        link.message.connect(self._on_message)
        if speed is not None:
            speed.busyChanged.connect(self._on_speed_busy)
            speed.stepped.connect(self._on_speed_step)
            speed.reached.connect(self._on_speed_reached)
            speed.failed.connect(self._on_speed_failed)
            speed.overspeed.connect(self._on_overspeed)
            self._apply_limit()

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

    def _limit(self) -> float:
        return float(self.limit_combo.currentData())

    def _apply_limit(self) -> None:
        if self.speed is not None:
            self.speed.max_speed = self._limit()

    def _set_speed(self) -> None:
        if self.speed is None:
            return
        target = float(self.speed_combo.currentData())
        if target > self._limit():
            self._log(f"{fmt_speed(target)} is above the limit; using {fmt_speed(self._limit())}")
            target = self._limit()
        self.speed.set_target(target)

    # --- speed events -----------------------------------------------------------------
    def _on_speed_busy(self, busy: bool) -> None:
        self.speed_button.setEnabled(not busy and self.link.connected)
        if busy and self.speed.target is not None:
            self.speed_status.setStyleSheet("")
            self.speed_status.setText(f"Setting {fmt_speed(self.speed.target)}…")

    def _on_speed_step(self, step: Step, before: float) -> None:
        self._log(f"speed key {STEP_KEYS[step]} (at {fmt_speed(before)})")

    def _on_speed_reached(self, target: float) -> None:
        self.speed_status.setStyleSheet("")
        self.speed_status.setText(f"Speed set to {fmt_speed(target)}")

    def _on_speed_failed(self, message: str) -> None:
        self.speed_status.setStyleSheet("color: #c62828;")
        self.speed_status.setText(f"Speed not set: {message}")
        self._log(f"speed: {message}")

    def _on_overspeed(self, rate: float) -> None:
        self._log(f"replay ran at {fmt_speed(rate)}, above the {fmt_speed(self._limit())} limit: paused")

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
        self.speed_button.setEnabled(connected and not (self.speed and self.speed.busy))

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
