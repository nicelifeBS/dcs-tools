"""Main window: connection, clock, play/pause, seeking with pre/post-roll, and speed."""

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
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..dcs.keys import Step
from ..dcs.link import DcsLink
from ..dcs.protocol import Arrived, Disarmed, Error, Hello, Message, Pong, State
from ..dcs.speed import SpeedController
from ..seek import Phase, SeekController, SeekError
from ..timefmt import fmt_model, fmt_speed, fmt_tod, parse_clock, tod_to_model

REFRESH_MS = 50
SPEED_CHOICES = (0.25, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
LIMIT_CHOICES = (1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
DEFAULT_LIMIT = 4
DEFAULT_PREROLL_S = 5.0
STEP_KEYS = {Step.UP: "LCtrl+Z", Step.DOWN: "LAlt+Z", Step.NORMAL: "LShift+Z"}
MODE_REPLAY, MODE_MISSION = "replay", "mission"
ERROR_STYLE = "color: #c62828;"


class MainWindow(QMainWindow):
    def __init__(self, link: DcsLink, speed: SpeedController | None = None,
                 seek: SeekController | None = None) -> None:
        super().__init__()
        self.link = link
        self.speed = speed
        self.seek = seek
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
        self.play_button.clicked.connect(self._play_clicked)

        # seek
        self.goto_edit = QLineEdit()
        self.goto_edit.setPlaceholderText("1:07.95")
        self.goto_edit.returnPressed.connect(self._go)
        self.goto_mode = QComboBox()
        self.goto_mode.addItem("replay time", MODE_REPLAY)
        self.goto_mode.addItem("mission time", MODE_MISSION)
        self.goto_mode.setToolTip("Replay time counts from the start of the track (the big clock). "
                                  "Mission time is the in-game clock, e.g. 16:31:07.")
        self.go_button = QPushButton("Go")
        self.go_button.clicked.connect(self._go)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self.preroll_spin = QDoubleSpinBox()
        self.preroll_spin.setRange(0.0, 600.0)
        self.preroll_spin.setDecimals(1)
        self.preroll_spin.setSuffix(" s")
        self.preroll_spin.setValue(DEFAULT_PREROLL_S)
        self.preroll_spin.setToolTip("Pause this long before the target.")
        self.postroll_spin = QDoubleSpinBox()
        self.postroll_spin.setRange(0.0, 600.0)
        self.postroll_spin.setDecimals(1)
        self.postroll_spin.setSuffix(" s")
        self.postroll_spin.setSpecialValueText("off")
        self.postroll_spin.setToolTip("After arriving, Play runs through the target and pauses this "
                                      "long after it. Off: Play just plays on.")
        self.seek_status = QLabel()
        self.seek_status.setWordWrap(True)
        goto_row = QHBoxLayout()
        goto_row.addWidget(QLabel("Go to"))
        goto_row.addWidget(self.goto_edit, 1)
        goto_row.addWidget(self.goto_mode)
        goto_row.addWidget(self.go_button)
        goto_row.addWidget(self.cancel_button)
        roll_row = QHBoxLayout()
        roll_row.addWidget(QLabel("Pre-roll"))
        roll_row.addWidget(self.preroll_spin)
        roll_row.addSpacing(16)
        roll_row.addWidget(QLabel("Post-roll"))
        roll_row.addWidget(self.postroll_spin)
        roll_row.addStretch(1)
        goto_box = QGroupBox("Seek")
        goto_layout = QVBoxLayout(goto_box)
        goto_layout.addLayout(goto_row)
        goto_layout.addLayout(roll_row)
        goto_layout.addWidget(self.seek_status)
        goto_box.setEnabled(seek is not None)

        # speed
        self.limit_combo = QComboBox()
        for x in LIMIT_CHOICES:
            self.limit_combo.addItem(fmt_speed(x), x)
        self.limit_combo.setCurrentIndex(LIMIT_CHOICES.index(DEFAULT_LIMIT))
        self.limit_combo.setToolTip("Seeks run at this speed, and the replay never runs faster: "
                                    "if it does (for example after pressing the keys in DCS by hand) "
                                    "it is paused and brought back down to this speed.")
        self.limit_combo.currentIndexChanged.connect(self._apply_limit)
        self.speed_combo = QComboBox()
        for x in SPEED_CHOICES:
            self.speed_combo.addItem(fmt_speed(x), x)
        self.speed_combo.setCurrentIndex(SPEED_CHOICES.index(1))
        self.speed_combo.setToolTip("Speed for watching: used after a seek arrives, and by Set.")
        self.speed_button = QPushButton("Set")
        self.speed_button.clicked.connect(self._set_speed)
        self.speed_status = QLabel()
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Seek at"))
        speed_row.addWidget(self.limit_combo)
        speed_row.addSpacing(16)
        speed_row.addWidget(QLabel("Playback"))
        speed_row.addWidget(self.speed_combo)
        speed_row.addWidget(self.speed_button)
        speed_row.addStretch(1)
        speed_box = QGroupBox("Speed")
        speed_layout = QVBoxLayout(speed_box)
        speed_layout.addLayout(speed_row)
        speed_layout.addWidget(self.speed_status)
        speed_box.setEnabled(speed is not None)

        # log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)

        root = QVBoxLayout()
        root.addLayout(top)
        root.addLayout(clock_box)
        root.addWidget(self.play_button)
        root.addWidget(goto_box)
        root.addWidget(speed_box)
        root.addWidget(self.log_view, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(600, 620)

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
        if seek is not None:
            seek.phaseChanged.connect(self._on_seek_phase)
            seek.ready.connect(self._on_seek_ready)
            seek.segmentDone.connect(self._on_segment_done)
            seek.failed.connect(self._on_seek_failed)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._on_connected(link.connected)
        self.refresh()

    # --- helpers ----------------------------------------------------------------------
    def _limit(self) -> float:
        return float(self.limit_combo.currentData())

    def _playback(self) -> float:
        return min(float(self.speed_combo.currentData()), self._limit())

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    @staticmethod
    def _status(label: QLabel, text: str, error: bool = False) -> None:
        label.setStyleSheet(ERROR_STYLE if error else "")
        label.setText(text)

    def _update_enabled(self) -> None:
        connected = self.link.connected
        seek_busy = self.seek is not None and self.seek.busy
        speed_busy = self.speed is not None and self.speed.busy
        self.play_button.setEnabled(connected and not seek_busy)
        self.go_button.setEnabled(connected and not seek_busy)
        self.cancel_button.setEnabled(self.seek is not None and self.seek.phase is not Phase.IDLE)
        self.speed_button.setEnabled(connected and not speed_busy and not seek_busy)
        self.limit_combo.setEnabled(not seek_busy)

    def _set_play_button(self, paused: bool) -> None:
        # Standard icons instead of ▶/⏸ characters, which some fonts lack.
        icon = QStyle.StandardPixmap.SP_MediaPlay if paused else QStyle.StandardPixmap.SP_MediaPause
        self.play_button.setIcon(self.style().standardIcon(icon))
        sk = self.seek
        if paused and sk is not None and sk.phase is Phase.READY and sk.postroll > 0:
            self.play_button.setText(f"Play through (pauses {sk.postroll:g} s after the target)")
        else:
            self.play_button.setText("Play" if paused else "Pause")

    # --- actions ----------------------------------------------------------------------
    def _play_clicked(self) -> None:
        s = self.link.state
        if s is None:
            return
        if not s.paused:
            self.link.pause()
        elif self.seek is not None:
            self.seek.play()
        else:
            self.link.resume()

    def _target_time(self) -> float:
        """The typed target as model time. Raises ValueError with a readable message."""
        text = self.goto_edit.text().strip()
        if not text:
            raise ValueError("Enter a time to go to.")
        try:
            t = parse_clock(text)
        except ValueError:
            raise ValueError(f"'{text}' is not a time; use 1:07.95, 67.95 or 16:31:07.") from None
        if self.goto_mode.currentData() == MODE_MISSION:
            s = self.link.state
            if s is None or s.start_tod is None:
                raise ValueError("DCS has not reported the mission start time yet.")
            t = tod_to_model(t, s.start_tod)
        return t

    def _go(self) -> None:
        if self.seek is None:
            return
        try:
            target = self._target_time()
            self.seek.seek(target, preroll=self.preroll_spin.value(), postroll=self.postroll_spin.value(),
                           seek_speed=self._limit(), playback_speed=self._playback())
        except (ValueError, SeekError) as exc:
            text = str(exc)
            self._status(self.seek_status, text[:1].upper() + text[1:], error=True)
            return
        self._log(f"seek to {fmt_model(target)}, pre-roll {self.preroll_spin.value():g} s, "
                  f"at {fmt_speed(self._limit())}")

    def _cancel(self) -> None:
        if self.seek is not None and self.seek.phase is not Phase.IDLE:
            self.seek.cancel()
            self._status(self.seek_status, "Seek cancelled.")
            self._log("seek cancelled")

    def _apply_limit(self) -> None:
        if self.speed is not None:
            self.speed.max_speed = self._limit()

    def _set_speed(self) -> None:
        if self.speed is None:
            return
        target = float(self.speed_combo.currentData())
        if target > self._limit():
            self._log(f"{fmt_speed(target)} is above the {fmt_speed(self._limit())} limit; "
                      f"using {fmt_speed(self._limit())}")
            target = self._limit()
        self.speed.set_target(target)

    # --- seek events ------------------------------------------------------------------
    def _on_seek_phase(self, phase: Phase) -> None:
        sk = self.seek
        texts = {
            Phase.PAUSING: "Pausing…",
            Phase.SPEEDING: f"Setting the seek speed ({fmt_speed(sk.seek_speed)})…",
            Phase.ARMING: "Arming the stop…",
            Phase.RUNNING: f"Seeking to {fmt_model(sk.stop_t)} at {fmt_speed(sk.seek_speed)}…",
            Phase.SLOWING: f"Arrived; setting playback speed ({fmt_speed(sk.playback_speed)})…",
            Phase.SEGMENT_ARMING: "Arming the post-roll stop…",
            Phase.SEGMENT: f"Playing through the target; pausing at "
                           f"{fmt_model((sk.event_t or 0) + sk.postroll)}…",
        }
        if phase in texts:
            self._status(self.seek_status, texts[phase])
        self._update_enabled()
        s = self.link.state
        if s is not None:
            self._set_play_button(s.paused)

    def _on_seek_ready(self, event_t: float, stop_t: float) -> None:
        sk = self.seek
        then = (f"Play runs through it and pauses {sk.postroll:g} s after." if sk.postroll > 0
                else "Press Play.")
        self._status(self.seek_status, f"Ready: paused at {fmt_model(stop_t)}, {event_t - stop_t:g} s before "
                                       f"the target at {fmt_model(event_t)}. {then}")
        self._log(f"ready at {fmt_model(stop_t)} (target {fmt_model(event_t)})")

    def _on_segment_done(self, t: float) -> None:
        after = t - (self.seek.event_t or t)
        self._status(self.seek_status, f"Paused at {fmt_model(t)}, {after:.1f} s after the target.")
        self._log(f"post-roll done at {fmt_model(t)}")

    def _on_seek_failed(self, message: str) -> None:
        self._status(self.seek_status, f"Seek stopped: {message}", error=True)
        self._log(f"seek failed: {message}")

    # --- speed events -----------------------------------------------------------------
    def _on_speed_busy(self, busy: bool) -> None:
        self._update_enabled()
        if busy and self.speed.target is not None:
            self._status(self.speed_status, f"Setting {fmt_speed(self.speed.target)}…")

    def _on_speed_step(self, step: Step, before: float) -> None:
        self._log(f"speed key {STEP_KEYS[step]} (at {fmt_speed(before)})")

    def _on_speed_reached(self, target: float) -> None:
        self._status(self.speed_status, f"Speed set to {fmt_speed(target)}")

    def _on_speed_failed(self, message: str) -> None:
        self._status(self.speed_status, f"Speed not set: {message}", error=True)
        self._log(f"speed: {message}")

    def _on_overspeed(self, rate: float) -> None:
        self._log(f"replay ran at {fmt_speed(rate)}, above the {fmt_speed(self._limit())} limit: paused")

    # --- link events ------------------------------------------------------------------
    def _on_connected(self, connected: bool) -> None:
        if connected:
            version = self.link.hook_version or "?"
            self.conn_label.setText(f"● Connected to DCS (hook {version})")
            self.conn_label.setStyleSheet("color: #2e7d32;")
        else:
            self.conn_label.setText("○ Waiting for DCS: start a track replay with the hook installed")
            self.conn_label.setStyleSheet("color: #9e9e9e;")
        self._update_enabled()

    def _on_state(self, s: State) -> None:
        parts = [p for p in (s.theatre, s.date) if p]
        if not s.track:
            parts.append("(not a track replay)")
        self.mission_label.setText("  ".join(parts))
        self._set_play_button(s.paused)

    def _on_message(self, msg: Message) -> None:
        if isinstance(msg, Arrived):
            self._log(f"paused at {msg.t:.3f} ({msg.over:.3f} s after the stop)")
        elif isinstance(msg, Disarmed) and msg.reason != "request":
            self._log(f"stop dropped: {msg.reason}")
        elif isinstance(msg, Error):
            self._log(f"DCS: {msg.text}")
        elif isinstance(msg, (Hello, Pong)):
            self._on_connected(self.link.connected)
            if isinstance(msg, Hello):
                self._log(f"hook {msg.version} connected")

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
