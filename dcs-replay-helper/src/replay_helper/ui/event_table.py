"""The Tacview event list: load an .acmi, filter its events, pick one to seek to."""

from __future__ import annotations

import bisect
import threading
from datetime import date
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QAbstractTableModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QRect,
    QSortFilterProxyModel,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..dcs.trk import TrackError, TrackInfo, read_track
from ..settings import Settings
from ..tacview.acmi import AcmiError, AcmiFile, read_acmi
from ..tacview.events import Event, Kind, build_events
from ..timefmt import fmt_model, fmt_tod
from ..timesync import SyncResult, SyncSettings, compute, fine_for_sync, fmt_tz

PAST_COLOR = QColor("#9e9e9e")
ERROR_STYLE = "color: #c62828;"
MIN_LEAD_S = 0.2  # matches seek.MIN_LEAD_S: a pre-roll point closer than this is behind
PAST_KEEP_S = 5.0  # an event stays listed (grayed) this long after it happens, to sync on it
COLLAPSE_MS = 400  # how long past events take to scroll out of the list

# Text color by side, as (light theme, dark theme): toned down so they read on either background.
SIDE_COLORS = {
    "blue": ("#2b5c9e", "#82aee6"),
    "red": ("#a83434", "#e88a8a"),
}

# Filter checkboxes: label, kinds, checked by default
FILTERS = (
    ("Bookmarks", (Kind.BOOKMARK,), True),
    ("Launches", (Kind.LAUNCH,), False),
    ("Kills", (Kind.DESTROYED,), False),
    ("Ejections", (Kind.EJECTION,), False),
    ("Take-off / landing", (Kind.TAKEOFF, Kind.LANDING), False),
    ("Other", (Kind.MESSAGE, Kind.OTHER), False),
)

COL_TIME, COL_TOD, COL_KIND, COL_LABEL, COL_UNITS = range(5)
HEADERS = ("Replay time", "Mission time", "Kind", "Event", "Units")


class EventTableModel(QAbstractTableModel):
    """Events in time order. Times shown are DCS replay times: ACMI time + offset."""

    goneChanged = Signal(int)  # the new gone_count

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._events: list[Event] = []
        self._times: list[float] = []  # DCS times, sorted
        self.offset = 0.0
        self.start_tod: float | None = None
        self._past = 0  # rows [0, _past) can no longer be reached
        self._gone = 0  # rows [0, _gone) happened more than PAST_KEEP_S ago
        self._last_now: float | None = None  # kept while DCS is away, so gone rows stay gone
        self._side_brushes: dict[str, QBrush] = {}
        self.set_dark(False)

    # --- data -------------------------------------------------------------------------
    def set_events(self, events: list[Event], offset: float = 0.0) -> None:
        self.beginResetModel()
        self._events = sorted(events, key=lambda e: e.t)
        self.offset = offset
        self._times = [e.t + offset for e in self._events]
        self._past = 0
        self._gone = self._gone_for(self._last_now)
        self.endResetModel()
        self.goneChanged.emit(self._gone)

    def set_offset(self, offset: float) -> None:
        if offset == self.offset:
            return
        self.offset = offset
        self._times = [e.t + offset for e in self._events]
        self._past = 0  # recomputed on the next set_now
        if self._events:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._events) - 1, len(HEADERS) - 1))
        self._set_gone(self._gone_for(self._last_now))

    def set_dark(self, dark: bool) -> None:
        """Pick the side colors for a dark or a light background."""
        self._side_brushes = {side: QBrush(QColor(pair[dark])) for side, pair in SIDE_COLORS.items()}
        if self._events:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._events) - 1, len(HEADERS) - 1),
                                  [Qt.ItemDataRole.ForegroundRole])

    def event_at(self, row: int) -> Event:
        return self._events[row]

    def dcs_time(self, row: int) -> float:
        return self._times[row]

    def is_past(self, row: int) -> bool:
        return row < self._past

    @property
    def past_count(self) -> int:
        return self._past

    @property
    def gone_count(self) -> int:
        """Rows [0, gone_count) happened more than PAST_KEEP_S before the replay clock."""
        return self._gone

    def set_now(self, now: float | None, preroll: float) -> None:
        """Gray out the events whose pre-roll point is behind `now`, and count those long gone.

        While DCS is away (`now` is None) nothing is grayed, but gone events stay gone.
        """
        past = 0 if now is None else bisect.bisect_right(self._times, now + preroll + MIN_LEAD_S)
        if past != self._past:
            lo, hi = sorted((past, self._past))
            self._past = past
            self.dataChanged.emit(self.index(lo, 0), self.index(hi - 1, len(HEADERS) - 1))
        if now is not None:
            self._last_now = now
            self._set_gone(self._gone_for(now))

    def _gone_for(self, now: float | None) -> int:
        return 0 if now is None else bisect.bisect_left(self._times, now - PAST_KEEP_S)

    def _set_gone(self, gone: int) -> None:
        if gone != self._gone:
            self._gone = gone
            self.goneChanged.emit(gone)

    def set_start_tod(self, start_tod: float | None) -> None:
        if start_tod != self.start_tod:
            self.start_tod = start_tod
            if self._events:
                self.dataChanged.emit(self.index(0, COL_TOD), self.index(len(self._events) - 1, COL_TOD))

    # --- Qt model ---------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._events)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        # Past rows stay selectable (to sync on them) but cannot be sought to.
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        e = self._events[row]
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_TIME:
                return fmt_model(self._times[row])
            if col == COL_TOD:
                return "" if self.start_tod is None else fmt_tod(self.start_tod + self._times[row])
            if col == COL_KIND:
                return e.kind.value
            if col == COL_LABEL:
                return e.label
            if col == COL_UNITS:
                return e.units
        elif role == Qt.ItemDataRole.ForegroundRole:
            if self.is_past(row):
                return QBrush(PAST_COLOR)
            return self._side_brushes.get(e.side.lower())
        elif role == Qt.ItemDataRole.ToolTipRole:
            if self.is_past(row):
                return "Behind the replay (replays only run forward); you can still sync on it"
            if col in (COL_LABEL, COL_UNITS):
                return e.label if col == COL_LABEL else e.units
        elif role == Qt.ItemDataRole.UserRole:
            return e
        return None


class EventFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.kinds: set[Kind] = {k for _, kinds, on in FILTERS if on for k in kinds}
        self.text = ""
        self.hide_before = 0  # source rows before this are past and out of the list

    def _refilter(self, change) -> None:
        # Qt 6.10 replaced invalidateFilter() with begin/endFilterChange(); support both.
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            change()
            self.endFilterChange()
        else:  # pragma: no cover - older Qt
            change()
            self.invalidateFilter()

    def set_kinds(self, kinds: set[Kind]) -> None:
        self._refilter(lambda: setattr(self, "kinds", kinds))

    def set_text(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "text", text.strip().lower()))

    def set_hide_before(self, source_row: int) -> None:
        if source_row != self.hide_before:
            self._refilter(lambda: setattr(self, "hide_before", source_row))

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if source_row < self.hide_before:
            return False
        e: Event = self.sourceModel().event_at(source_row)
        if e.kind not in self.kinds:
            return False
        return not self.text or self.text in e.label.lower() or self.text in e.units.lower()


class AcmiLoader(QObject):
    """Reads an ACMI file on a worker thread."""

    loaded = Signal(object, object)  # AcmiFile, list[Event]
    failed = Signal(str, str)  # path, message
    progress = Signal(float)

    def load(self, path: str | Path) -> None:
        threading.Thread(target=self._run, args=(Path(path),), name="acmi-reader", daemon=True).start()

    def _run(self, path: Path) -> None:
        try:
            f = read_acmi(path, progress=self.progress.emit)
            events = build_events(f)
        except (AcmiError, OSError) as exc:
            self.failed.emit(str(path), str(exc))
            return
        except Exception as exc:  # a malformed file must not take the app down
            self.failed.emit(str(path), f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(f, events)


class CollapseDelegate(QStyledItemDelegate):
    """Draws a row shorter than the default height against its bottom edge, clipped.

    Past rows leave the list by shrinking to nothing; drawn like this, they look like they
    scroll off the top rather than squash.
    """

    def __init__(self, table: QTableView) -> None:
        super().__init__(table)
        self.table = table

    def paint(self, painter, option, index) -> None:
        full = self.table.verticalHeader().defaultSectionSize()
        rect = option.rect
        if rect.height() >= full:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        opt.rect = QRect(rect.left(), rect.bottom() + 1 - full, rect.width(), full)
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        super().paint(painter, opt, index)
        painter.restore()


class EventPanel(QWidget):
    """Open a recording, filter its events, and ask for a seek to one of them."""

    seekRequested = Signal(object, float)  # Event, DCS replay time
    fileLoaded = Signal(object)  # AcmiFile
    synced = Signal(str)  # a sentence for the log
    filtersChanged = Signal(list)  # labels of the checked kind filters

    def __init__(self, settings: Settings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.acmi: AcmiFile | None = None
        self.track: TrackInfo | None = None
        self.sync = SyncSettings()
        self.result: SyncResult | None = None
        self._now: float | None = None
        self._dcs_start_tod: float | None = None
        self._dcs_date: str | None = None
        self.model = EventTableModel(self)
        self.model.goneChanged.connect(lambda _gone: self._sync_hidden())
        self.proxy = EventFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.loader = AcmiLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.progress.connect(lambda x: self.progress.setValue(int(x * 100)))

        self.open_button = QPushButton("Open Tacview recording…")
        self.open_button.clicked.connect(self.browse_acmi)
        self.file_label = QLabel("No recording loaded")
        self.file_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)

        self.checks: list[tuple[QCheckBox, tuple[Kind, ...]]] = []
        filter_row = QHBoxLayout()
        for label, kinds, on in FILTERS:
            box = QCheckBox(label)
            box.setChecked(on)
            box.toggled.connect(self._apply_kinds)
            filter_row.addWidget(box)
            self.checks.append((box, kinds))
        filter_row.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search events and units")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        self.show_past = QCheckBox("Show past events")
        self.show_past.setToolTip("Keep the events the replay has passed in the list, grayed out. "
                                  f"Otherwise they scroll away {PAST_KEEP_S:g} s after they happen.")
        self.show_past.setChecked(bool(settings.get("show_past_events")) if settings else False)
        self.show_past.toggled.connect(self._show_past_toggled)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.show_past)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setItemDelegate(CollapseDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_LABEL, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(COL_UNITS, 180)
        self.table.doubleClicked.connect(lambda _index: self._request_seek())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_go())

        self.go_button = QPushButton("Go to event")
        self.go_button.clicked.connect(self._request_seek)
        self.go_button.setEnabled(False)
        self.go_enabled = True  # cleared by the window while a seek runs or DCS is away

        # past events leaving the list: the top proxy rows shrink away, then are filtered out
        self._collapsing = 0  # proxy rows [0, _collapsing) are shrinking
        self._collapse_to = 0  # proxy.hide_before once they are gone
        self._row_height = 0
        self.collapse = QVariantAnimation(self)
        self.collapse.setStartValue(0.0)
        self.collapse.setEndValue(1.0)
        self.collapse.setDuration(COLLAPSE_MS)
        self.collapse.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.collapse.valueChanged.connect(self._collapse_step)
        self.collapse.finished.connect(self._collapse_finished)
        self._update_side_colors()

        # time sync
        self.sync_info = QLabel()
        self.sync_info.setWordWrap(True)
        self.sync_warning = QLabel()
        self.sync_warning.setWordWrap(True)
        self.sync_warning.setStyleSheet(ERROR_STYLE)
        self.sync_warning.setVisible(False)
        self.tz_auto = QCheckBox("Auto time zone")
        self.tz_auto.setChecked(True)
        self.tz_auto.setToolTip("Tacview times are UTC; the mission clock is local time on the map. "
                                "Auto takes the difference between the two start times, to 15 minutes.")
        self.tz_auto.toggled.connect(self._tz_auto_toggled)
        self.tz_spin = QDoubleSpinBox()
        self.tz_spin.setRange(-12.0, 14.0)
        self.tz_spin.setSingleStep(0.25)
        self.tz_spin.setDecimals(2)
        self.tz_spin.setPrefix("UTC ")
        self.tz_spin.setSuffix(" h")
        self.tz_spin.setEnabled(False)
        self.tz_spin.valueChanged.connect(self._tz_changed)
        self.fine_spin = QDoubleSpinBox()
        self.fine_spin.setRange(-86400.0, 86400.0)
        self.fine_spin.setDecimals(2)
        self.fine_spin.setSingleStep(0.1)
        self.fine_spin.setSuffix(" s")
        self.fine_spin.setToolTip("Added to every Tacview time. Sync to selected event sets it for you.")
        self.fine_spin.valueChanged.connect(self._fine_changed)
        self.sync_button = QPushButton("Sync to selected event")
        self.sync_button.setToolTip("Pause DCS exactly when the selected event happens, then click: "
                                    "the fine adjustment is set so that event lands on the replay clock.")
        self.sync_button.clicked.connect(self._sync_to_selected)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(lambda: self._set_sync(SyncSettings()))
        self.track_button = QPushButton("Open track…")
        self.track_button.setToolTip("Read the mission start time from the .trk you are replaying, "
                                     "to check the times before DCS runs.")
        self.track_button.clicked.connect(self.browse_track)
        self.track_label = QLabel()
        self.track_label.setWordWrap(True)
        tz_row = QHBoxLayout()
        tz_row.addWidget(self.tz_auto)
        tz_row.addWidget(self.tz_spin)
        tz_row.addSpacing(12)
        tz_row.addWidget(QLabel("Fine"))
        tz_row.addWidget(self.fine_spin)
        tz_row.addStretch(1)
        button_row = QHBoxLayout()
        button_row.addWidget(self.sync_button)
        button_row.addWidget(self.reset_button)
        button_row.addStretch(1)
        button_row.addWidget(self.track_button)
        sync_box = QGroupBox("Time sync")
        sync_layout = QVBoxLayout(sync_box)
        sync_layout.addWidget(self.sync_info)
        sync_layout.addLayout(tz_row)
        sync_layout.addLayout(button_row)
        sync_layout.addWidget(self.track_label)
        sync_layout.addWidget(self.sync_warning)

        top = QHBoxLayout()
        top.addWidget(self.open_button)
        top.addWidget(self.file_label, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.go_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.progress)
        layout.addWidget(sync_box)
        layout.addLayout(filter_row)
        layout.addLayout(search_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

    # --- loading ----------------------------------------------------------------------
    def _last_dir(self, key: str) -> str:
        value = self.settings.get(key) if self.settings else None
        return value if isinstance(value, str) else ""

    def _remember_dir(self, key: str, path: str) -> None:
        if self.settings is not None:
            self.settings.set(key, str(Path(path).parent))

    def browse_acmi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Tacview recording", self._last_dir("last_acmi_dir"),
            "Tacview recordings (*.acmi);;All files (*)")
        if path:
            self._remember_dir("last_acmi_dir", path)
            self.load(path)

    def load(self, path: str | Path) -> None:
        self.open_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.file_label.setStyleSheet("")
        self.file_label.setText(f"Reading {Path(path).name}…")
        self.loader.load(path)

    def _on_loaded(self, f: AcmiFile, events: list[Event]) -> None:
        self.acmi = f
        self._settle()
        self.model.set_events(events, offset=self.model.offset)
        self.sync = self.settings.sync_for(f.path) if self.settings else SyncSettings()
        self._show_sync_settings()
        self._recompute()
        self._fit_columns()
        self.open_button.setEnabled(True)
        self.progress.setVisible(False)
        counts = {}
        for e in events:
            counts[e.kind] = counts.get(e.kind, 0) + 1
        bookmarks = counts.get(Kind.BOOKMARK, 0)
        title = f" — {f.title}" if f.title else ""
        self.file_label.setText(f"{f.path.name}{title}\n{bookmarks} bookmark{'s' * (bookmarks != 1)}, "
                                f"{len(events)} events")
        self.file_label.setToolTip(str(f.path))
        self._update_go()
        self.fileLoaded.emit(f)

    def _on_failed(self, path: str, message: str) -> None:
        self.open_button.setEnabled(True)
        self.progress.setVisible(False)
        self.file_label.setStyleSheet("color: #c62828;")
        self.file_label.setText(f"Could not read {Path(path).name}: {message}")

    # --- filtering and picking --------------------------------------------------------
    def _apply_kinds(self) -> None:
        kinds = {k for box, ks in self.checks if box.isChecked() for k in ks}
        self._settle()
        self.proxy.set_kinds(kinds)
        self._fit_columns()
        self._update_go()
        self.filtersChanged.emit([box.text() for box, _ in self.checks if box.isChecked()])

    def set_checked_filters(self, labels: list[str]) -> None:
        for box, _ in self.checks:
            box.blockSignals(True)
            box.setChecked(box.text() in labels)
            box.blockSignals(False)
        self._apply_kinds()

    def _search_changed(self, text: str) -> None:
        self._settle()
        self.proxy.set_text(text)
        self._update_go()

    def _show_past_toggled(self, on: bool) -> None:
        if self.settings is not None:
            self.settings.set("show_past_events", on)
        self._sync_hidden()

    # --- past events scrolling away ---------------------------------------------------
    def _hidden_target(self) -> int:
        return 0 if self.show_past.isChecked() else self.model.gone_count

    def _sync_hidden(self) -> None:
        """Bring the rows hidden as past in line with the model; animate the ones leaving."""
        target = self._hidden_target()
        if self._collapsing:
            if target >= self._collapse_to:
                return  # the rest leave when this collapse ends
            self._settle()  # rows came back (track restarted, offset changed)
        current = self.proxy.hide_before
        if target == current:
            return
        leaving = 0  # visible rows that go
        while leaving < self.proxy.rowCount() and \
                self.proxy.mapToSource(self.proxy.index(leaving, 0)).row() < target:
            leaving += 1
        bar = self.table.verticalScrollBar()
        height = sum(self.table.rowHeight(r) for r in range(leaving))
        if target < current or not leaving or not self.table.isVisible() or bar.value() >= height:
            # Nothing to see go: change the list at once, keeping the rows in view where they are.
            value = bar.value()
            self._set_hidden(target)
            if target > current:
                bar.setValue(value - height)
            return
        self._collapsing, self._collapse_to = leaving, target
        self._row_height = self.table.verticalHeader().defaultSectionSize()
        self.collapse.start()

    def _collapse_step(self, value: float) -> None:
        height = round(self._row_height * (1.0 - value))
        for r in range(self._collapsing):
            self.table.setRowHeight(r, height)

    def _collapse_finished(self) -> None:
        self._settle()
        self._sync_hidden()  # more may have gone meanwhile

    def _settle(self) -> None:
        """End a running collapse now: its rows leave the list."""
        if not self._collapsing:
            return
        if self.collapse.state() != QAbstractAnimation.State.Stopped:
            self.collapse.stop()
        for r in range(self._collapsing):
            self.table.setRowHeight(r, self._row_height)
        self._collapsing = 0
        self._set_hidden(self._collapse_to)

    def _set_hidden(self, source_row: int) -> None:
        self.proxy.set_hide_before(source_row)
        self._update_go()

    def _update_side_colors(self) -> None:
        self.model.set_dark(self.table.palette().base().color().lightnessF() < 0.5)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._update_side_colors()
        super().changeEvent(event)

    def _fit_columns(self) -> None:
        for col in (COL_TIME, COL_TOD, COL_KIND):
            self.table.resizeColumnToContents(col)

    def selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.proxy.mapToSource(rows[0]).row()

    def _update_go(self) -> None:
        row = self.selected_row()
        self.go_button.setEnabled(self.go_enabled and row is not None and not self.model.is_past(row))
        self.sync_button.setEnabled(row is not None and self._now is not None)

    def set_go_enabled(self, enabled: bool) -> None:
        self.go_enabled = enabled
        self._update_go()

    def _request_seek(self) -> None:
        row = self.selected_row()
        if row is None or self.model.is_past(row) or not self.go_enabled:
            return
        self.seekRequested.emit(self.model.event_at(row), self.model.dcs_time(row))

    def set_now(self, now: float | None, preroll: float, start_tod: float | None = None,
                mission_date: str | None = None) -> None:
        """Called by the window as the replay runs. None while DCS is not connected."""
        if (start_tod, mission_date) != (self._dcs_start_tod, self._dcs_date):
            self._dcs_start_tod, self._dcs_date = start_tod, mission_date
            self._recompute()
        had_now = self._now is not None
        self._now = now
        before = self.model.past_count
        self.model.set_now(now, preroll)
        if self.model.past_count != before or had_now != (now is not None):
            self._update_go()

    # --- time sync --------------------------------------------------------------------
    def _start_tod(self) -> tuple[float | None, str]:
        if self._dcs_start_tod is not None:
            return self._dcs_start_tod, "DCS"
        if self.track is not None and self.track.start_tod is not None:
            return self.track.start_tod, "track"
        return None, ""

    def _mission_date(self) -> date | None:
        text = self._dcs_date or (self.track.date if self.track else None)
        try:
            return date.fromisoformat(text) if text else None
        except ValueError:
            return None

    def _recompute(self) -> None:
        start_tod, source = self._start_tod()
        f = self.acmi
        ref_tod = f.reference_tod if f else None
        acmi_date = f.reference_time.date() if f and f.reference_time else None
        self.result = r = compute(self.sync, ref_tod, start_tod, acmi_date, self._mission_date())
        self.model.set_start_tod(start_tod)
        self.model.set_offset(r.offset)

        parts = []
        if f is None:
            parts.append("Open a recording to line its times up with the replay.")
        else:
            parts.append(f"Tacview starts {fmt_tod(ref_tod)} UTC" if ref_tod is not None
                         else "Tacview has no reference time")
            parts.append(f"mission starts {fmt_tod(start_tod)} (from {source})" if start_tod is not None
                         else "mission start unknown: connect DCS or open the track")
            if ref_tod is not None and start_tod is not None:
                parts.append(f"time zone {fmt_tz(r.tz_minutes)}{' (auto)' if r.auto else ''}")
            parts.append(f"replay time = Tacview time {r.offset:+.2f} s")
        self.sync_info.setText(" · ".join(parts))
        self.sync_warning.setText(r.warning or "")
        self.sync_warning.setVisible(bool(r.warning))
        if r.auto and r.tz_minutes is not None:
            self.tz_spin.blockSignals(True)
            self.tz_spin.setValue(r.tz_minutes / 60)
            self.tz_spin.blockSignals(False)

    def _show_sync_settings(self) -> None:
        for w in (self.tz_auto, self.tz_spin, self.fine_spin):
            w.blockSignals(True)
        self.tz_auto.setChecked(self.sync.tz_minutes is None)
        self.tz_spin.setEnabled(self.sync.tz_minutes is not None)
        if self.sync.tz_minutes is not None:
            self.tz_spin.setValue(self.sync.tz_minutes / 60)
        self.fine_spin.setValue(self.sync.fine_s)
        for w in (self.tz_auto, self.tz_spin, self.fine_spin):
            w.blockSignals(False)

    def _set_sync(self, sync: SyncSettings) -> None:
        self.sync = sync
        if self.settings is not None and self.acmi is not None:
            self.settings.set_sync(self.acmi.path, sync)
        self._show_sync_settings()
        self._recompute()

    def _tz_auto_toggled(self, auto: bool) -> None:
        if auto:
            tz = None
        else:
            tz = self.result.tz_minutes if self.result and self.result.tz_minutes is not None else 0
        self._set_sync(SyncSettings(tz, self.sync.fine_s))

    def _tz_changed(self, hours: float) -> None:
        if not self.tz_auto.isChecked():
            self._set_sync(SyncSettings(int(round(hours * 4)) * 15, self.sync.fine_s))

    def _fine_changed(self, seconds: float) -> None:
        self._set_sync(SyncSettings(self.sync.tz_minutes, round(seconds, 2)))

    def _sync_to_selected(self) -> None:
        row = self.selected_row()
        if row is None or self._now is None or self.acmi is None:
            return
        e = self.model.event_at(row)
        start_tod, _ = self._start_tod()
        fine = fine_for_sync(self.sync, self.acmi.reference_tod, start_tod, e.t, self._now)
        self._set_sync(SyncSettings(self.sync.tz_minutes, round(fine, 2)))
        self.synced.emit(f"synced '{e.label}' to {fmt_model(self._now)}: replay time = Tacview time "
                         f"{self.result.offset:+.2f} s")

    def browse_track(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open the DCS track you are replaying",
                                              self._last_dir("last_trk_dir"),
                                              "DCS tracks (*.trk);;All files (*)")
        if path:
            self._remember_dir("last_trk_dir", path)
            self.load_track(path)

    def load_track(self, path: str | Path) -> None:
        try:
            self.track = read_track(path)
        except TrackError as exc:
            self.track_label.setStyleSheet(ERROR_STYLE)
            self.track_label.setText(f"Could not read {Path(path).name}: {exc}")
            return
        t = self.track
        bits = [p for p in (t.theatre, t.date) if p]
        if t.start_tod is not None:
            bits.append(f"starts {fmt_tod(t.start_tod)}")
        if t.duration is not None:
            bits.append(f"{fmt_model(t.duration)} long")
        self.track_label.setStyleSheet("")
        self.track_label.setText(f"Track {t.path.name}: " + ", ".join(bits))
        self.track_label.setToolTip(str(t.path))
        self._recompute()
