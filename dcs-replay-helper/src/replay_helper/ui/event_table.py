"""The Tacview event list: load an .acmi, filter its events, pick one to seek to."""

from __future__ import annotations

import bisect
import threading
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..tacview.acmi import AcmiError, AcmiFile, read_acmi
from ..tacview.events import Event, Kind, build_events
from ..timefmt import fmt_model, fmt_tod

PAST_COLOR = QColor("#9e9e9e")
MIN_LEAD_S = 0.2  # matches seek.MIN_LEAD_S: a pre-roll point closer than this is behind

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

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._events: list[Event] = []
        self._times: list[float] = []  # DCS times, sorted
        self.offset = 0.0
        self.start_tod: float | None = None
        self._past = 0  # rows [0, _past) can no longer be reached

    # --- data -------------------------------------------------------------------------
    def set_events(self, events: list[Event], offset: float = 0.0) -> None:
        self.beginResetModel()
        self._events = sorted(events, key=lambda e: e.t)
        self.offset = offset
        self._times = [e.t + offset for e in self._events]
        self._past = 0
        self.endResetModel()

    def event_at(self, row: int) -> Event:
        return self._events[row]

    def dcs_time(self, row: int) -> float:
        return self._times[row]

    def is_past(self, row: int) -> bool:
        return row < self._past

    @property
    def past_count(self) -> int:
        return self._past

    def set_now(self, now: float | None, preroll: float) -> None:
        """Gray out the events whose pre-roll point is behind `now`."""
        past = 0 if now is None else bisect.bisect_right(self._times, now + preroll + MIN_LEAD_S)
        if past != self._past:
            lo, hi = sorted((past, self._past))
            self._past = past
            self.dataChanged.emit(self.index(lo, 0), self.index(hi - 1, len(HEADERS) - 1))

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
        if self.is_past(index.row()):
            return Qt.ItemFlag.NoItemFlags  # replays only run forward
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
        elif role == Qt.ItemDataRole.ForegroundRole and self.is_past(row):
            return QBrush(PAST_COLOR)
        elif role == Qt.ItemDataRole.ToolTipRole:
            if self.is_past(row):
                return "Behind the replay: replays only run forward"
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

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
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


class EventPanel(QWidget):
    """Open a recording, filter its events, and ask for a seek to one of them."""

    seekRequested = Signal(object, float)  # Event, DCS replay time
    fileLoaded = Signal(object)  # AcmiFile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.acmi: AcmiFile | None = None
        self.model = EventTableModel(self)
        self.proxy = EventFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.loader = AcmiLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.progress.connect(lambda x: self.progress.setValue(int(x * 100)))

        self.open_button = QPushButton("Open Tacview recording…")
        self.open_button.clicked.connect(self._browse)
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
        self.search.textChanged.connect(self.proxy.set_text)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_LABEL, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(COL_UNITS, 180)
        self.table.doubleClicked.connect(lambda _index: self._request_seek())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_go())

        self.go_button = QPushButton("Go to event")
        self.go_button.clicked.connect(self._request_seek)
        self.go_button.setEnabled(False)
        self.go_enabled = True  # cleared by the window while a seek runs or DCS is away

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
        layout.addLayout(filter_row)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

    # --- loading ----------------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Tacview recording", "",
            "Tacview recordings (*.acmi);;All files (*)")
        if path:
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
        self.model.set_events(events, offset=self.model.offset)
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
        self.proxy.set_kinds(kinds)
        self._fit_columns()
        self._update_go()

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

    def set_go_enabled(self, enabled: bool) -> None:
        self.go_enabled = enabled
        self._update_go()

    def _request_seek(self) -> None:
        row = self.selected_row()
        if row is None or self.model.is_past(row) or not self.go_enabled:
            return
        self.seekRequested.emit(self.model.event_at(row), self.model.dcs_time(row))

    def set_now(self, now: float | None, preroll: float, start_tod: float | None) -> None:
        self.model.set_start_tod(start_tod)
        before = self.model.past_count
        self.model.set_now(now, preroll)
        if self.model.past_count != before:
            row = self.selected_row()
            if row is not None and self.model.is_past(row):
                self.table.clearSelection()
            self._update_go()
