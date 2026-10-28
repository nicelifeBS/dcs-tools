"""Aircraft, helicopters and missiles with their speeds, and a button that sets the free
camera's speed to follow the selected one (see dcs/camera.py)."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..dcs.link import DcsLink
from ..dcs.protocol import Error, Obj, ObjEnd, State

POLL_MS = 1000
MS_TO_KT = 1.943844
MS_TO_KMH = 3.6
UNITS = (("kt", MS_TO_KT), ("km/h", MS_TO_KMH), ("m/s", 1.0))
KIND_NAMES = {"plane": "Aircraft", "heli": "Helicopter", "weapon": "Missile", "air": "Air"}
COLUMNS = ("Type", "Pilot / unit", "Group", "Speed", "Along the view", "Distance")
KIND_FILTERS = (("plane", "Aircraft"), ("heli", "Helicopters"), ("weapon", "Missiles"))
DEFAULT_RADIUS_KM = 20
DEFAULT_KEYS = 30
COALITION_COLORS = {"blue": "#1565c0", "red": "#c62828"}
ERROR_STYLE = "color: #c62828;"


def fmt_ms(value: float | None, factor: float, unit: str, signed: bool = False) -> str:
    if value is None:
        return "?"
    text = f"{value * factor:+.0f}" if signed else f"{value * factor:.0f}"
    return f"{text} {unit}"


def fmt_distance(m: float | None) -> str:
    if m is None:
        return "?"
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


def describe(o: Obj) -> str:
    """How the log and the status line name an object."""
    who = o.unit or o.group or o.type or str(o.id)
    return f"{who} ({o.type})" if o.type and o.type != who else who


def along_text(o: Obj, factor: float, unit: str) -> str:
    """The speed the camera must have: signed, with the direction in words."""
    if o.along is None:
        return "?"
    word = "forward" if o.along >= 0 else "backward"
    return f"{abs(o.along) * factor:.0f} {unit} {word}"


class ObjectPanel(QWidget):
    matchRequested = Signal(int, str)  # DCS id, label
    cancelRequested = Signal()
    keysChanged = Signal(int)  # key presses per round

    def __init__(self, link: DcsLink, settings=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.link = link
        self.settings = settings
        self._objects: dict[int, Obj] = {}
        self._incoming: list[Obj] = []
        self._busy = False

        self.kind_checks: dict[str, QCheckBox] = {}
        filters = QHBoxLayout()
        for kind, label in KIND_FILTERS:
            check = QCheckBox(label)
            check.setChecked(True)
            check.toggled.connect(self._rebuild)
            self.kind_checks[kind] = check
            filters.addWidget(check)
        filters.addSpacing(12)
        filters.addWidget(QLabel("Within"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 500)
        self.radius_spin.setValue(DEFAULT_RADIUS_KM)
        self.radius_spin.setSuffix(" km")
        self.radius_spin.setToolTip("Only objects this close to the camera are listed.")
        filters.addWidget(self.radius_spin)
        filters.addSpacing(12)
        filters.addWidget(QLabel("Speed in"))
        self.unit_combo = QComboBox()
        for name, factor in UNITS:
            self.unit_combo.addItem(name, factor)
        self.unit_combo.currentIndexChanged.connect(self._rebuild)
        filters.addWidget(self.unit_combo)
        filters.addStretch(1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._match())

        self.camera_label = QLabel()
        self.match_button = QPushButton("Match camera speed")
        self.match_button.setToolTip(
            "Set the free camera's (F11) speed to the selected object's speed along the camera's "
            "view axis, with the keys and mouse wheel of DCS. The DCS window comes to the front "
            "and the mouse pointer moves over it for a moment. Paused, the replay runs in slow "
            "motion meanwhile and is paused again after.")
        self.match_button.clicked.connect(self._match)
        self.keys_spin = QSpinBox()
        self.keys_spin.setRange(1, 60)
        self.keys_spin.setValue(DEFAULT_KEYS)
        self.keys_spin.setToolTip("Key presses (LAlt+Num* / Num/) sent at once in each round. More is faster, "
                                  "but if DCS misses presses, lower it.")
        self.keys_spin.valueChanged.connect(self.keysChanged.emit)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.hint = QLabel(
            "The speeds are worked out from how far each object moved, so they show after the "
            "replay has played for a moment. The camera can only fly along the way it looks: "
            "look along the object's flight path (or straight back at it) to follow it.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")

        buttons = QHBoxLayout()
        buttons.addWidget(self.match_button)
        buttons.addWidget(self.cancel_button)
        buttons.addSpacing(12)
        buttons.addWidget(QLabel("Key presses per round"))
        buttons.addWidget(self.keys_spin)
        buttons.addStretch(1)
        buttons.addWidget(self.camera_label)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(self.hint)

        link.message.connect(self._on_message)
        link.stateChanged.connect(self._on_state)
        link.connectedChanged.connect(lambda _on: self._update_buttons())
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        self._restore()
        self._update_buttons()

    # --- settings ---------------------------------------------------------------------
    def _restore(self) -> None:
        st = self.settings
        if st is None:
            return
        i = self.unit_combo.findText(str(st.get("object_unit", "kt")))
        if i >= 0:
            self.unit_combo.setCurrentIndex(i)
        if isinstance(st.get("object_radius_km"), int):
            self.radius_spin.setValue(st.get("object_radius_km"))
        if isinstance(st.get("camera_keys"), int):
            self.keys_spin.setValue(st.get("camera_keys"))
        self.keys_spin.valueChanged.connect(lambda v: st.set("camera_keys", v))
        saved = st.get("object_kinds")
        if isinstance(saved, list):
            for kind, check in self.kind_checks.items():
                check.setChecked(kind in saved)
        self.unit_combo.currentIndexChanged.connect(lambda: st.set("object_unit", self.unit_combo.currentText()))
        self.radius_spin.valueChanged.connect(lambda v: st.set("object_radius_km", v))
        for check in self.kind_checks.values():
            check.toggled.connect(lambda _on: st.set("object_kinds", self.checked_kinds()))

    def checked_kinds(self) -> list[str]:
        return [k for k, c in self.kind_checks.items() if c.isChecked()]

    # --- polling ----------------------------------------------------------------------
    def poll(self) -> None:
        """Ask for the objects (and make sure the hook is measuring them) once a second."""
        if not (self.link.connected and self.link.reports_objects and self.isVisible()):
            return
        self.link.track(True)  # idempotent; the hook forgets it when a mission loads
        self.link.request_objects(self.radius_spin.value() * 1000)

    def _on_message(self, msg) -> None:
        if isinstance(msg, Obj):
            self._incoming.append(msg)
        elif isinstance(msg, ObjEnd):
            self._objects = {o.id: o for o in self._incoming}
            self._incoming = []
            self._rebuild()
        elif isinstance(msg, Error) and msg.text.startswith("OBJECTS needs TRACK"):
            self.link.track(True)

    def _on_state(self, s: State) -> None:
        if s.cam is None:
            self.camera_label.setText("Camera speed: unknown (free camera, F11?)")
            return
        factor, unit = self._unit()
        word = "backward" if s.cam < -0.05 else "forward"
        self.camera_label.setText(f"Camera speed: {abs(s.cam) * factor:.0f} {unit} {word}")

    # --- table ------------------------------------------------------------------------
    def _unit(self) -> tuple[float, str]:
        return float(self.unit_combo.currentData()), self.unit_combo.currentText()

    def selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def visible_objects(self) -> list[Obj]:
        kinds = set(self.checked_kinds())
        shown = [o for o in self._objects.values() if o.kind in kinds or (o.kind == "air" and "plane" in kinds)]
        shown.sort(key=lambda o: (o.dist is None, o.dist or 0.0, o.id))
        return shown

    def _rebuild(self) -> None:
        keep = self.selected_id()
        factor, unit = self._unit()
        shown = self.visible_objects()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(shown))
        for row, o in enumerate(shown):
            cells = (
                KIND_NAMES.get(o.kind, o.kind) + (f" {o.type}" if o.type else ""),
                (o.unit or "?") + (" (player)" if o.human else ""),
                o.group or "",
                fmt_ms(o.speed, factor, unit),
                along_text(o, factor, unit),
                fmt_distance(o.dist),
            )
            for col, text in enumerate(cells):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, o.id)
                color = COALITION_COLORS.get((o.coalition or "").lower())
                item.setForeground(self.palette().text() if color is None else _brush(color))
            if o.id == keep:
                self.table.selectRow(row)
        self.table.setUpdatesEnabled(True)
        self._update_buttons()

    # --- match ------------------------------------------------------------------------
    def selected_object(self) -> Obj | None:
        oid = self.selected_id()
        return None if oid is None else self._objects.get(oid)

    def _match(self) -> None:
        o = self.selected_object()
        if o is None or self._busy:
            return
        self.set_status("")
        self.matchRequested.emit(o.id, describe(o))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_buttons()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet(ERROR_STYLE if error else "")
        self.status.setText(text)

    def _update_buttons(self) -> None:
        ready = self.link.connected and self.link.reports_objects
        o = self.selected_object()
        self.match_button.setEnabled(ready and not self._busy and o is not None)
        self.cancel_button.setEnabled(self._busy)
        if self.link.connected and not self.link.reports_objects and self.link.hook_version is not None:
            self.set_status("The DCS hook is too old for this: Tools > Install / update DCS hook, then restart DCS.",
                            error=True)


def _brush(color: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(color))
