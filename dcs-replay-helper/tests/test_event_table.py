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
    assert m.flags(m.index(0, 0)) & Qt.ItemFlag.ItemIsSelectable  # selectable for syncing
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
    assert panel.selected_row() == 0  # past rows can be selected (to sync on them)...
    assert not panel.go_button.isEnabled()  # ...but not sought to
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


def test_sync_panel(qapp) -> None:
    from replay_helper.settings import Settings
    from replay_helper.ui.event_table import EventPanel

    settings = Settings()
    panel = EventPanel(settings)
    panel.load(str(SAMPLE))
    assert wait_until(qapp, lambda: panel.acmi is not None)
    info = panel.sync_info.text()
    assert "Tacview starts 12:30:00 UTC" in info and "mission start unknown" in info
    assert panel.model.dcs_time(0) == pytest.approx(67.95)

    panel.set_now(10.0, 5.0, 59400, "2018-02-01")  # DCS connected: mission starts 16:30
    info = panel.sync_info.text()
    assert "mission starts 16:30:00 (from DCS)" in info
    assert "time zone UTC+4:00 (auto)" in info and "Tacview time +0.00 s" in info
    assert panel.tz_spin.value() == 4.0 and not panel.tz_spin.isEnabled()
    assert panel.model.data(panel.model.index(0, 1)) == "16:31:07"

    panel.tz_auto.setChecked(False)  # manual time zone, starting from the auto value
    panel.tz_spin.setValue(3.0)
    assert panel.result.offset == pytest.approx(-3600)
    assert "time zone UTC+3:00" in panel.sync_info.text()
    panel.tz_auto.setChecked(True)
    assert panel.result.offset == 0

    # Pause DCS on the moment "Running in" happens -- 2.05 s later than Tacview says -- and sync.
    synced = []
    panel.synced.connect(synced.append)
    panel.set_now(70.0, 5.0, 59400, "2018-02-01")
    panel.table.selectRow(0)
    assert panel.sync_button.isEnabled()
    panel.sync_button.click()
    assert panel.fine_spin.value() == pytest.approx(2.05)
    assert panel.model.dcs_time(0) == pytest.approx(70.0)
    assert synced and "replay time = Tacview time +2.05 s" in synced[0]

    # Saved per recording: a new panel picks it up.
    again = EventPanel(Settings())
    again.load(str(SAMPLE))
    assert wait_until(qapp, lambda: again.acmi is not None)
    assert again.fine_spin.value() == pytest.approx(2.05) and again.result.offset == pytest.approx(2.05)
    again.reset_button.click()
    assert again.result.offset == 0 and Settings().sync_for(SAMPLE).fine_s == 0


def test_sync_from_track_before_dcs_runs(qapp) -> None:
    from replay_helper.ui.event_table import EventPanel

    panel = EventPanel()
    panel.load(str(SAMPLE))
    assert wait_until(qapp, lambda: panel.acmi is not None)
    panel.load_track(str(SAMPLE.with_name("sample_caucasus.trk")))
    assert "Track sample_caucasus.trk: Caucasus, 2018-02-01, starts 16:30:00, 1:57.1 long" in \
        panel.track_label.text()
    assert "mission starts 16:30:00 (from track)" in panel.sync_info.text()
    assert "UTC+4:00 (auto)" in panel.sync_info.text()
    assert not panel.sync_button.isEnabled()  # needs DCS for the replay clock
    panel.load_track(str(SAMPLE))  # not a track
    assert panel.track_label.text().startswith("Could not read")


def test_date_mismatch_warns(qapp) -> None:
    from replay_helper.ui.event_table import EventPanel

    panel = EventPanel()
    panel.load(str(SAMPLE))
    assert wait_until(qapp, lambda: panel.acmi is not None)
    panel.set_now(10.0, 5.0, 59400, "2024-06-01")
    assert panel.sync_warning.isVisibleTo(panel)
    assert "is it the recording of this track?" in panel.sync_warning.text()
