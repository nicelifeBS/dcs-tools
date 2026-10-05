"""Main window: connection, clock, play/pause, seeking with a pre-roll, stops before bookmarks,
speed, Tacview events."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..dcs.keys import Step
from ..dcs.link import DcsLink
from ..dcs.protocol import Arrived, Disarmed, Error, Focused, FocusFailed, Hello, Message, Pong, State
from .. import hook_installer
from ..dcs.speed import SpeedController
from ..seek import Phase, SeekController, SeekError
from ..settings import Settings
from ..stops import BookmarkStops, Stop
from ..tacview.events import Event, dcs_unit_id
from ..timefmt import fmt_model, fmt_speed, fmt_tod, parse_clock, tod_to_model
from .event_table import EventPanel

REFRESH_MS = 50
SPEED_CHOICES = (0.25, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
LIMIT_CHOICES = (1, 2, 3, 4, 5, 6, 8, 10, 12, 16)
DEFAULT_LIMIT = 4
DEFAULT_PREROLL_S = 5.0
STEP_KEYS = {Step.UP: "LCtrl+Z", Step.DOWN: "LAlt+Z", Step.NORMAL: "LShift+Z"}
MODE_REPLAY, MODE_MISSION = "replay", "mission"
ERROR_STYLE = "color: #c62828;"
FOCUS_REASONS = {
    "not_found": "it is not in the replay at this point",
    "cycled": "F2 never showed it",
    "max_steps": "F2 never showed it",
    "no_camera": "DCS did not report the camera",
    "unavailable": "DCS did not take the view command",
    "cancelled": "cancelled",
    "restart": "the track restarted",
    "mission_end": "the mission ended",
}


class MainWindow(QMainWindow):
    def __init__(self, link: DcsLink, speed: SpeedController | None = None,
                 seek: SeekController | None = None, settings: Settings | None = None) -> None:
        super().__init__()
        self.link = link
        self.speed = speed
        self.seek = seek
        self.settings = settings
        self.saved_games_dir: Path | None = None  # None: ask Windows (tests point it elsewhere)
        self._seek_event_obj: Event | None = None  # the event the current seek goes to, if any
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
        self.preroll_spin.setToolTip("Pause this long before the target, and before each bookmark "
                                     "with Stop before bookmarks.")
        self.stops_check = QCheckBox("Stop before bookmarks")
        self.stops_check.setChecked(True)
        self.stops_check.setToolTip("While the replay plays, pause it the pre-roll before the next Tacview "
                                    "bookmark, so it never runs past one. The camera and the speed are "
                                    "left as they are. Seeks jump past bookmarks, and Play after a seek "
                                    "runs through its target.")
        self.focus_check = QCheckBox("Show the event's aircraft (F2)")
        self.focus_check.setChecked(True)
        self.focus_check.setToolTip("When you jump to an event from the list, switch DCS to the F2 view of "
                                    "the aircraft involved once it arrives: the shooter, the lost or "
                                    "ejecting aircraft, or the one a bookmark names. Stops before "
                                    "bookmarks never move the camera.")
        self.seek_status = QLabel()
        self.seek_status.setWordWrap(True)
        self.stop_status = QLabel()
        self.stop_status.setWordWrap(True)
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
        roll_row.addWidget(self.stops_check)
        roll_row.addSpacing(16)
        roll_row.addWidget(self.focus_check)
        roll_row.addStretch(1)
        goto_box = QGroupBox("Seek")
        goto_layout = QVBoxLayout(goto_box)
        goto_layout.addLayout(goto_row)
        goto_layout.addLayout(roll_row)
        goto_layout.addWidget(self.seek_status)
        goto_layout.addWidget(self.stop_status)
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

        # Tacview events
        self.events = EventPanel(settings)
        self.events.seekRequested.connect(self._seek_event)
        self.events.synced.connect(self._log)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addLayout(top)
        left.addLayout(clock_box)
        left.addWidget(self.play_button)
        left.addWidget(goto_box)
        left.addWidget(speed_box)
        left.addWidget(self.log_view, 1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        self.splitter = splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.events)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 640])
        central = QWidget()
        root = QVBoxLayout(central)
        root.addWidget(splitter)
        self.setCentralWidget(central)
        self.resize(1220, 660)
        self._build_menus()

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
            seek.failed.connect(self._on_seek_failed)
        # Stops before bookmarks keep the hook's stop between seeks, so they need the seek.
        self.stops = BookmarkStops(link, seek, self) if seek is not None else None
        if self.stops is not None:
            self.stops.armedChanged.connect(self._on_stop_armed)
            self.stops.reached.connect(self._on_stop_reached)
            self.stops.set_preroll(self.preroll_spin.value())
            self.preroll_spin.valueChanged.connect(self.stops.set_preroll)
            self.stops_check.toggled.connect(self.stops.set_enabled)
            self.events.model.bookmarksChanged.connect(self.stops.set_bookmarks)
        else:
            self.stops_check.setEnabled(False)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._on_connected(link.connected)
        self._restore_settings()
        self.refresh()

    # --- menus ------------------------------------------------------------------------
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_acmi = QAction("&Open Tacview recording…", self)
        open_acmi.setShortcut(QKeySequence.StandardKey.Open)
        open_acmi.triggered.connect(self.events.browse_acmi)
        file_menu.addAction(open_acmi)
        open_trk = QAction("Open &track…", self)
        open_trk.triggered.connect(self.events.browse_track)
        file_menu.addAction(open_trk)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        tools_menu = self.menuBar().addMenu("&Tools")
        self.install_action = QAction("&Install / update DCS hook…", self)
        self.install_action.triggered.connect(lambda: self.install_hook())
        tools_menu.addAction(self.install_action)

    # --- DCS hook -----------------------------------------------------------------------
    def _dcs_dirs(self) -> list[Path]:
        return hook_installer.find_dcs_dirs(self.saved_games_dir)

    def check_hook(self) -> list[hook_installer.HookStatus]:
        """Log the hook's state in each DCS folder; nudge towards installing when needed."""
        dirs = self._dcs_dirs()
        if not dirs:
            self._log("no DCS folder found in Saved Games; use Tools > Install / update DCS hook")
            return []
        statuses = [hook_installer.hook_status(d) for d in dirs]
        for st in statuses:
            self._log(f"{st.dcs_dir.name}: {st.describe()}")
        if any(st.needs_install for st in statuses):
            self._log("use Tools > Install / update DCS hook, then restart DCS")
        return statuses

    def install_hook(self, confirm: bool = True) -> list[hook_installer.HookStatus]:
        dirs = self._dcs_dirs()
        if not dirs:
            if not confirm:
                return []
            chosen = QFileDialog.getExistingDirectory(
                self, "Choose your DCS folder in Saved Games (e.g. Saved Games\\DCS)",
                str(hook_installer.saved_games_dir()))
            if not chosen:
                return []
            dirs = [Path(chosen)]
        statuses = [hook_installer.hook_status(d) for d in dirs]
        todo = [st for st in statuses if st.needs_install]
        if not todo:
            lines = "\n".join(f"{st.dcs_dir}: {st.describe()}" for st in statuses)
            if confirm:
                QMessageBox.information(self, "DCS hook", f"Nothing to do.\n\n{lines}")
            return statuses
        if confirm:
            lines = "\n".join(f"• {st.dcs_dir}\n    now: {st.describe()}" for st in todo)
            answer = QMessageBox.question(
                self, "Install DCS hook",
                f"Install the Replay Helper hook {todo[0].bundled_version} into:\n\n{lines}\n\n"
                f"It goes into Scripts\\Hooks; nothing is written to the DCS install folder.")
            if answer != QMessageBox.StandardButton.Yes:
                return statuses
        done = []
        for st in todo:
            try:
                done.append(hook_installer.install(st.dcs_dir))
                self._log(f"installed hook {st.bundled_version} into {st.hook_path}")
            except OSError as exc:
                self._log(f"could not install into {st.dcs_dir}: {exc}")
                if confirm:
                    QMessageBox.warning(self, "DCS hook", f"Could not install into {st.dcs_dir}:\n{exc}")
        if done and confirm:
            QMessageBox.information(self, "DCS hook", "Installed. Restart DCS to load the hook.")
        return done

    # --- remembered settings ------------------------------------------------------------
    def _restore_settings(self) -> None:
        st = self.settings
        if st is None:
            return

        def pick(combo: QComboBox, value) -> None:
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)

        pick(self.limit_combo, st.get("seek_speed"))
        pick(self.speed_combo, st.get("playback_speed"))
        pick(self.goto_mode, st.get("goto_mode"))
        if isinstance(st.get("preroll"), (int, float)):
            self.preroll_spin.setValue(st.get("preroll"))
        if isinstance(st.get("focus_aircraft"), bool):
            self.focus_check.setChecked(st.get("focus_aircraft"))
        if isinstance(st.get("stop_at_bookmarks"), bool):
            self.stops_check.setChecked(st.get("stop_at_bookmarks"))
        if isinstance(st.get("event_filters"), list):
            self.events.set_checked_filters(st.get("event_filters"))
        for key, restore in (("geometry", self.restoreGeometry), ("splitter", self.splitter.restoreState)):
            value = st.get(key)
            if isinstance(value, str):
                restore(QByteArray.fromBase64(value.encode("ascii")))

        self.limit_combo.currentIndexChanged.connect(lambda: st.set("seek_speed", self.limit_combo.currentData()))
        self.speed_combo.currentIndexChanged.connect(lambda: st.set("playback_speed", self.speed_combo.currentData()))
        self.goto_mode.currentIndexChanged.connect(lambda: st.set("goto_mode", self.goto_mode.currentData()))
        self.preroll_spin.valueChanged.connect(lambda v: st.set("preroll", v))
        self.events.filtersChanged.connect(lambda labels: st.set("event_filters", labels))
        self.focus_check.toggled.connect(lambda on: st.set("focus_aircraft", on))
        self.stops_check.toggled.connect(lambda on: st.set("stop_at_bookmarks", on))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.settings is not None:
            self.settings.set("geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
            self.settings.set("splitter", bytes(self.splitter.saveState().toBase64()).decode("ascii"))
        super().closeEvent(event)

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
        self.events.set_go_enabled(connected and not seek_busy and self.seek is not None)

    def _set_play_button(self, paused: bool) -> None:
        # Standard icons instead of ▶/⏸ characters, which some fonts lack.
        icon = QStyle.StandardPixmap.SP_MediaPlay if paused else QStyle.StandardPixmap.SP_MediaPause
        self.play_button.setIcon(self.style().standardIcon(icon))
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
        try:
            target = self._target_time()
        except ValueError as exc:
            self._status(self.seek_status, str(exc), error=True)
            return
        self._start_seek(target, fmt_model(target))

    def _seek_event(self, event: Event, t: float) -> None:
        """A seek picked from the Tacview event list."""
        self.goto_mode.setCurrentIndex(self.goto_mode.findData(MODE_REPLAY))
        self.goto_edit.setText(f"{t:.2f}")
        self._start_seek(t, f"{event.kind.value.lower()} '{event.label}' at {fmt_model(t)}", event)

    def _start_seek(self, target: float, what: str, event: Event | None = None) -> None:
        if self.seek is None:
            return
        self._seek_event_obj = event
        try:
            self.seek.seek(target, preroll=self.preroll_spin.value(), seek_speed=self._limit(),
                           playback_speed=self._playback())
        except SeekError as exc:
            text = str(exc)
            self._status(self.seek_status, text[:1].upper() + text[1:], error=True)
            return
        self._log(f"seek to {what}, pre-roll {self.preroll_spin.value():g} s, at {fmt_speed(self._limit())}")

    def load_acmi(self, path: str) -> None:
        self.events.load(path)

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
        }
        if phase in texts:
            self._status(self.seek_status, texts[phase])
        self._update_enabled()
        s = self.link.state
        if s is not None:
            self._set_play_button(s.paused)

    def _on_seek_ready(self, event_t: float, stop_t: float) -> None:
        self._status(self.seek_status, f"Ready: paused at {fmt_model(stop_t)}, {event_t - stop_t:g} s before "
                                       f"the target at {fmt_model(event_t)}. Press Play.")
        self._log(f"ready at {fmt_model(stop_t)} (target {fmt_model(event_t)})")
        self._focus_event_aircraft()

    def _focus_event_aircraft(self) -> None:
        """F2 on the aircraft of the event just jumped to; only seeks to a picked event do this."""
        e = self._seek_event_obj
        if e is None or e.aircraft is None or not self.focus_check.isChecked():
            return
        who = e.aircraft_unit or f"#{e.aircraft:x}"
        if not self.link.takes_actions:
            self._log(f"can't show {who} in F2: update the DCS hook (Tools > Install / update DCS hook)")
            return
        self._log(f"showing {who} in F2…")
        self.link.focus(dcs_unit_id(e.aircraft), e.aircraft_unit)

    def _on_seek_failed(self, message: str) -> None:
        self._status(self.seek_status, f"Seek stopped: {message}", error=True)
        self._log(f"seek failed: {message}")

    # --- stops before bookmarks ---------------------------------------------------------
    @staticmethod
    def _before(stop: Stop) -> str:
        lead = stop.bookmark_t - stop.t
        when = f"{lead:g} s before" if lead > 0 else "at"
        return f"{when} bookmark '{stop.label}' at {fmt_model(stop.bookmark_t)}"

    def _on_stop_armed(self, stop: Stop | None) -> None:
        self.stop_status.setText("" if stop is None else f"Next stop: {fmt_model(stop.t)}, {self._before(stop)}")

    def _on_stop_reached(self, stop: Stop, t: float) -> None:
        # The camera stays where it is: only a jump to an event moves it.
        self._status(self.seek_status, f"Stopped at {fmt_model(t)}, {self._before(stop)}. Press Play.")
        self._log(f"stopped {self._before(stop)}")

    # --- speed events -----------------------------------------------------------------
    def _on_speed_busy(self, busy: bool) -> None:
        self._update_enabled()
        if busy and self.speed.target is not None:
            self._status(self.speed_status, f"Setting {fmt_speed(self.speed.target)}…")

    def _on_speed_step(self, step: Step, before: float) -> None:
        how = f"step {step.value.lower()}" if self.link.takes_actions else f"key {STEP_KEYS[step]}"
        self._log(f"speed {how} (at {fmt_speed(before)})")

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
            bundled = hook_installer.hook_version(hook_installer.bundled_hook())
            if self.link.hook_version and not self.link.hook_version.startswith("fake") and \
                    hook_installer.version_key(self.link.hook_version) < hook_installer.version_key(bundled):
                self.conn_label.setText(f"● Connected to DCS (hook {version}; {bundled} available: "
                                        "Tools > Install / update DCS hook)")
                self.conn_label.setStyleSheet("color: #ef6c00;")
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
        elif isinstance(msg, Focused):
            e = self._seek_event_obj
            who = e.aircraft_unit if e is not None and e.aircraft is not None and \
                dcs_unit_id(e.aircraft) == msg.id and e.aircraft_unit else f"unit {msg.id}"
            steps = f" ({msg.steps} step{'s' * (msg.steps != 1)})" if msg.steps else ""
            self._log(f"F2 view on {who}{steps}")
        elif isinstance(msg, FocusFailed):
            if msg.reason != "cancelled":
                self._log(f"could not show the aircraft in F2: {FOCUS_REASONS.get(msg.reason, msg.reason)}")
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
        connected = s is not None and self.link.connected
        self.events.set_now(t, self.preroll_spin.value(), s.start_tod if connected else None,
                            s.date if connected else None)
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
