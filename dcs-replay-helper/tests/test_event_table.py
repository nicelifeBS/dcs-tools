from __future__ import annotations

from pathlib import Path

import pytest

from conftest import WIDGETS, wait_until

pytestmark = pytest.mark.skipif(not WIDGETS, reason="Qt widgets unavailable (libEGL missing)")

SAMPLE = Path(__file__).parent / "data" / "sample_caucasus.zip.acmi"


def events():
    from replay_helper.tacview.acmi import read_acmi
    from replay_helper.tacview.events import build_events

    return build_events(read_acmi(SAMPLE))


def test_model_grays_out_events_behind_the_replay(qapp) -> None:
    from PySide6.QtCore import Qt

    from replay_helper.ui.event_table import COL_LABEL, COL_TIME, COL_TOD, EventTableModel

    m = EventTableModel()
    m.set_events(events())
    m.set_start_tod(59400)
    assert m.rowCount() == 5
    assert m.data(m.index(0, COL_TIME)) == "1:08.0"
    assert m.data(m.index(0, COL_TOD)) == "16:31:07"
    assert m.data(m.index(0, COL_LABEL)) == "Running in"

    m.set_now(60.0, preroll=5)  # Running in (67.95) needs the replay before 62.75
    assert m.past_count == 0
    m.set_now(63.0, preroll=5)
    assert m.past_count == 1 and m.is_past(0) and not m.is_past(1)
    assert m.flags(m.index(0, 0)) == Qt.ItemFlag.NoItemFlags
    assert m.data(m.index(0, 0), Qt.ItemDataRole.ForegroundRole) is not None
    m.set_now(None, preroll=5)  # disconnected: nothing is known to be past
    assert m.past_count == 0


def test_offset_shifts_dcs_times(qapp) -> None:
    from replay_helper.ui.event_table import EventTableModel

    m = EventTableModel()
    m.set_events(events(), offset=-10)
    assert m.dcs_time(0) == pytest.approx(57.95)


def test_filters(qapp) -> None:
    from replay_helper.tacview.events import Kind
    from replay_helper.ui.event_table import EventFilterProxy, EventTableModel

    m = EventTableModel()
    m.set_events(events())
    proxy = EventFilterProxy()
    proxy.setSourceModel(m)
    assert proxy.rowCount() == 2  # bookmarks by default
    proxy.set_kinds({Kind.BOOKMARK, Kind.LAUNCH, Kind.DESTROYED, Kind.EJECTION})
    assert proxy.rowCount() == 5
    proxy.set_text("agr")
    assert proxy.rowCount() == 1
    proxy.set_text("NICELIFE")  # matches labels and units, any case
    assert proxy.rowCount() == 3


def test_panel_loads_and_requests_seek(qapp) -> None:
    from replay_helper.ui.event_table import EventPanel

    panel = EventPanel()
    requests = []
    panel.seekRequested.connect(lambda e, t: requests.append((e.label, t)))
    panel.load(str(SAMPLE))
    assert wait_until(qapp, lambda: panel.acmi is not None)
    assert "2 bookmarks, 5 events" in panel.file_label.text()
    assert panel.proxy.rowCount() == 2

    panel.set_now(80.0, 5.0, 59400)  # Running in is behind now; idiot (88.01) is not
    panel.table.selectRow(0)
    assert panel.selected_row() is None  # past rows cannot be selected
    panel.table.selectRow(1)
    assert panel.go_button.isEnabled()
    panel.go_button.click()
    assert requests == [("idiot", pytest.approx(88.01))]

    panel.set_go_enabled(False)  # e.g. while a seek runs
    assert not panel.go_button.isEnabled()


def test_panel_reports_unreadable_files(qapp, tmp_path) -> None:
    from replay_helper.ui.event_table import EventPanel

    bad = tmp_path / "bad.acmi"
    bad.write_text("not tacview")
    panel = EventPanel()
    panel.load(str(bad))
    assert wait_until(qapp, lambda: panel.file_label.text().startswith("Could not read"))
    assert "not a Tacview ACMI" in panel.file_label.text()
    assert panel.open_button.isEnabled()
