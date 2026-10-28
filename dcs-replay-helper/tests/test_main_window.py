"""Headless runs of the main window against the fake DCS."""

from __future__ import annotations

import re

import pytest

from conftest import WIDGETS, wait_until

pytestmark = pytest.mark.skipif(not WIDGETS, reason="Qt widgets unavailable (libEGL missing)")


@pytest.fixture
def app_rig(qapp, fake_dcs_server):
    from replay_helper.dcs.camera import AutoCameraInput, CameraMatcher
    from replay_helper.dcs.link import DcsLink
    from replay_helper.dcs.speed import AutoKeyBackend, SpeedController
    from replay_helper.seek import SeekController
    from replay_helper.ui.main_window import MainWindow

    made = []

    def make(time_scale: float = 1.0, **sim_kwargs):
        sim, state_port, cmd_port = fake_dcs_server(time_scale=time_scale, **sim_kwargs)
        link = DcsLink(state_port=state_port, cmd_port=cmd_port)
        assert link.start()
        speed = SpeedController(link, AutoKeyBackend(link))
        seek = SeekController(link, speed)
        camera = CameraMatcher(link, speed, AutoCameraInput(link))
        window = MainWindow(link, speed, seek, camera=camera)
        made.append((link, speed, window))
        return sim, link, window

    yield make
    for link, speed, window in made:
        speed.shutdown()
        link.stop()
        window.close()


def test_window_follows_dcs(qapp, app_rig) -> None:
    sim, link, window = app_rig(start=62.95, paused=True)
    assert "Waiting for DCS" in window.conn_label.text()
    assert not window.play_button.isEnabled()

    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    window.refresh()
    assert "Connected to DCS (hook fake-0.3.0)" in window.conn_label.text()
    assert window.clock_label.text() == "1:03.0"
    assert window.tod_label.text() == "Mission time 16:31:02"
    assert window.play_button.text() == "Play"
    assert window.mission_label.text() == "Caucasus  2018-02-01"

    window.play_button.click()
    assert wait_until(qapp, lambda: not link.state.paused)
    assert wait_until(qapp, lambda: window.play_button.text() == "Pause")
    window.play_button.click()
    assert wait_until(qapp, lambda: link.state.paused)


def test_window_sets_speed_within_limit(qapp, app_rig) -> None:
    sim, link, window = app_rig(paused=True)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)

    window.speed_combo.setCurrentIndex(window.speed_combo.findData(8))  # above the default 4x limit
    window.speed_button.click()
    assert wait_until(qapp, lambda: window.speed_status.text() == "Speed set to 4x")
    assert sim.accel == 4
    log = window.log_view.toPlainText()
    assert "8x is above the 4x limit; using 4x" in log
    assert log.count("speed step up") == 3  # by the hook: no keystrokes

    window.limit_combo.setCurrentIndex(window.limit_combo.findData(2))
    window.play_button.click()  # runs at 4x, above the new 2x limit -> paused, back to 2x
    assert wait_until(qapp, lambda: sim.accel == 2 and sim.paused)
    assert "above the 2x limit: paused" in window.log_view.toPlainText()


def test_window_seek_with_pre_roll(qapp, app_rig) -> None:
    sim, link, window = app_rig(start=50.0, time_scale=10)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)

    window.goto_edit.setText("16:32:00")  # mission time = replay 2:00
    window.goto_mode.setCurrentIndex(window.goto_mode.findData("mission"))
    window.preroll_spin.setValue(5)
    window.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Ready"), timeout=10), \
        window.seek_status.text()
    assert window.seek_status.text() == ("Ready: paused at 1:55.0, 5 s before the target at 2:00.0. "
                                         "Press Play.")
    assert 115.0 <= sim.t < 115.5 and sim.paused and sim.accel == 1 and sim.max_running_accel == 4
    assert window.play_button.text() == "Play"

    window.play_button.click()  # plays on through the target
    assert wait_until(qapp, lambda: window.play_button.text() == "Pause")
    assert wait_until(qapp, lambda: sim.t > 121.0, timeout=10) and not sim.paused


def test_window_seek_errors(qapp, app_rig) -> None:
    sim, link, window = app_rig(start=50.0, paused=True)
    assert wait_until(qapp, lambda: link.connected)

    window.goto_edit.setText("soon")
    window.go_button.click()
    assert window.seek_status.text() == "'soon' is not a time; use 1:07.95, 67.95 or 16:31:07."

    window.goto_edit.setText("0:52")  # replay time, but the pre-roll point (0:47) is behind 0:50
    window.go_button.click()
    assert "behind the replay" in window.seek_status.text()
    assert "only run forward" in window.seek_status.text()


def test_window_cancel_seek(qapp, app_rig) -> None:
    sim, link, window = app_rig(start=10.0, paused=True)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    window.limit_combo.setCurrentIndex(window.limit_combo.findData(1))  # slow, so it can be cancelled
    window.goto_edit.setText("100")
    window.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Seeking to"))
    assert not window.go_button.isEnabled() and window.cancel_button.isEnabled()
    window.cancel_button.click()
    assert window.seek_status.text() == "Seek cancelled."
    assert wait_until(qapp, lambda: sim.paused and sim.stop is None)
    assert window.go_button.isEnabled()


def test_window_seeks_to_a_tacview_bookmark(qapp, app_rig) -> None:
    from pathlib import Path

    sim, link, window = app_rig(start=50.0, time_scale=10)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    window.load_acmi(str(Path(__file__).parent / "data" / "sample_caucasus.zip.acmi"))
    panel = window.events
    assert wait_until(qapp, lambda: panel.acmi is not None)

    window.preroll_spin.setValue(5)
    panel.table.selectRow(1)  # "idiot" at 88.01
    panel.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Ready"), timeout=10), \
        window.seek_status.text()
    assert 83.01 <= sim.t < 83.6 and sim.paused
    assert window.goto_edit.text() == "88.01"
    assert "seek to bookmark 'idiot' at 1:28.0" in window.log_view.toPlainText()
    window.refresh()
    # Both bookmarks are now unreachable: Running in is behind, and the replay sits at idiot's
    # pre-roll point already.
    m = panel.model
    past = {m.event_at(r).label for r in range(m.rowCount()) if m.is_past(r)}
    assert {"Running in", "idiot"} <= past
    # The bookmark names the player's A-10C (Tacview 0x5701): F2 on DCS unit 0x1005700.
    assert wait_until(qapp, lambda: "F2 view on fubar 1-1 | nicelife (1 step)" in window.log_view.toPlainText())
    assert "showing fubar 1-1 | nicelife in F2…" in window.log_view.toPlainText()
    assert sim.focused == 0x1005700


def seek_to_idiot(qapp, app_rig, **sim_kwargs):
    from pathlib import Path

    sim, link, window = app_rig(start=50.0, time_scale=10, **sim_kwargs)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    window.load_acmi(str(Path(__file__).parent / "data" / "sample_caucasus.zip.acmi"))
    assert wait_until(qapp, lambda: window.events.acmi is not None)
    return sim, link, window


def go_to_idiot(qapp, window) -> None:
    window.events.table.selectRow(1)  # "idiot" at 88.01
    window.events.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Ready"), timeout=10)


def test_window_focus_can_be_switched_off(qapp, app_rig) -> None:
    sim, link, window = seek_to_idiot(qapp, app_rig)
    window.focus_check.setChecked(False)
    go_to_idiot(qapp, window)
    wait_until(qapp, lambda: False, timeout=0.3)
    assert sim.focused is None and "F2" not in window.log_view.toPlainText()


def test_window_reports_an_aircraft_dcs_does_not_have(qapp, app_rig) -> None:
    sim, link, window = seek_to_idiot(qapp, app_rig, aircraft=set())
    go_to_idiot(qapp, window)
    assert wait_until(qapp, lambda: "could not show the aircraft in F2: it is not in the replay at this point"
                      in window.log_view.toPlainText())


def test_window_with_an_old_hook_uses_keys_and_cannot_focus(qapp, app_rig, monkeypatch) -> None:
    from conftest import load_fake_dcs

    monkeypatch.setattr(load_fake_dcs(), "VERSION", "fake-0.1.0")
    sim, link, window = seek_to_idiot(qapp, app_rig)
    assert not link.takes_actions
    go_to_idiot(qapp, window)
    log = window.log_view.toPlainText()
    assert "speed key LCtrl+Z" in log  # the old fake takes KEY for keystrokes
    assert "can't show fubar 1-1 | nicelife in F2: update the DCS hook" in log
    assert sim.focused is None


def test_window_stops_before_bookmarks_and_leaves_the_camera(qapp, app_rig) -> None:
    sim, link, window = seek_to_idiot(qapp, app_rig, paused=True)
    # Bookmarks "Running in" at 67.95 and "idiot" at 88.01, pre-roll 5 s.
    assert wait_until(qapp, lambda: sim.stop == pytest.approx(62.95))
    assert window.stop_status.text() == "Next stop: 1:03.0, 5 s before bookmark 'Running in' at 1:08.0"

    window.play_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Stopped at"), timeout=10)
    assert re.fullmatch(r"Stopped at 1:03\.\d, 5 s before bookmark 'Running in' at 1:08\.0\. Press Play\.",
                        window.seek_status.text())
    assert sim.paused and 62.95 <= sim.t < 63.5
    assert window.stop_status.text() == "Next stop: 1:23.0, 5 s before bookmark 'idiot' at 1:28.0"
    assert sim.focused is None and "F2" not in window.log_view.toPlainText()  # camera left alone
    assert "stopped 5 s before bookmark 'Running in' at 1:08.0" in window.log_view.toPlainText()

    window.stops_check.setChecked(False)
    assert wait_until(qapp, lambda: sim.stop is None)
    assert window.stop_status.text() == ""
    assert wait_until(qapp, lambda: window.play_button.text() == "Play")  # on the next STATE
    window.play_button.click()
    assert wait_until(qapp, lambda: sim.t > 84.0, timeout=10) and not sim.paused  # runs past idiot's stop


def test_window_plays_through_the_event_it_jumped_to_and_stops_before_the_next(qapp, app_rig) -> None:
    sim, link, window = seek_to_idiot(qapp, app_rig, paused=True)
    window.events.table.selectRow(0)  # "Running in" at 67.95
    window.events.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Ready"), timeout=10)
    assert wait_until(qapp, lambda: sim.focused == 0x1005700)  # the jump shows the aircraft
    sim.focused = None  # the user picks another camera
    assert wait_until(qapp, lambda: sim.stop == pytest.approx(83.01))  # idiot; not Running in again

    window.play_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Stopped at"), timeout=10)
    assert sim.paused and 83.01 <= sim.t < 83.6 and sim.t > 67.95
    assert sim.focused is None


def test_hook_check_and_install(qapp, tmp_path) -> None:
    from replay_helper.dcs.link import DcsLink
    from replay_helper.ui.main_window import MainWindow

    saved = tmp_path / "Saved Games"
    (saved / "DCS" / "Logs").mkdir(parents=True)
    hooks = saved / "DCS" / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    (hooks / "ReplayHelperSpike.lua").write_text("-- spike")
    window = MainWindow(DcsLink())
    window.saved_games_dir = saved

    window.check_hook()
    log = window.log_view.toPlainText()
    assert "DCS: hook not installed; the spike hook" in log and "Tools > Install / update DCS hook" in log

    done = window.install_hook(confirm=False)
    assert [st.dcs_dir.name for st in done] == ["DCS"] and done[0].current
    assert (hooks / "ReplayHelper.lua").exists() and not (hooks / "ReplayHelperSpike.lua").exists()
    assert window.install_hook(confirm=False)[0].current  # nothing left to do
    window.close()


def test_settings_are_remembered(qapp) -> None:
    from replay_helper.dcs.link import DcsLink
    from replay_helper.settings import Settings
    from replay_helper.ui.main_window import MainWindow

    first = MainWindow(DcsLink(), settings=Settings())
    first.limit_combo.setCurrentIndex(first.limit_combo.findData(8))
    first.speed_combo.setCurrentIndex(first.speed_combo.findData(0.5))
    first.preroll_spin.setValue(12)
    first.stops_check.setChecked(False)
    first.goto_mode.setCurrentIndex(first.goto_mode.findData("mission"))
    first.focus_check.setChecked(False)
    first.events.checks[1][0].setChecked(True)  # Launches
    first.resize(1300, 700)
    first.close()

    second = MainWindow(DcsLink(), settings=Settings())
    assert second.limit_combo.currentData() == 8
    assert second.speed_combo.currentData() == 0.5
    assert second.preroll_spin.value() == 12
    assert not second.stops_check.isChecked()
    assert second.goto_mode.currentData() == "mission"
    assert not second.focus_check.isChecked()
    assert [box.isChecked() for box, _ in second.events.checks][:2] == [True, True]
    # Window size and splitter are stored (the headless test screen is too small to check the
    # restored size: Qt clamps windows to the screen).
    assert isinstance(Settings().get("geometry"), str) and isinstance(Settings().get("splitter"), str)
    second.close()


# --- camera speed ----------------------------------------------------------------------------
def objects_tab(qapp, window):
    window.show()
    window.tabs.setCurrentWidget(window.objects)
    window.objects.radius_spin.setValue(20)  # the fake aircraft are several km apart
    return window.objects


def select(panel, unit: str) -> None:
    for row in range(panel.table.rowCount()):
        if panel.table.item(row, 1).text().startswith(unit):
            panel.table.selectRow(row)
            return
    raise AssertionError(f"{unit} is not listed")


def test_lists_objects_with_speeds_group_and_pilot(qapp, app_rig) -> None:
    sim, link, window = app_rig(time_scale=4)
    panel = objects_tab(qapp, window)
    assert wait_until(qapp, lambda: panel.table.rowCount() == 3, timeout=8)
    rows = {panel.table.item(r, 1).text(): [panel.table.item(r, c).text() for c in range(6)]
            for r in range(panel.table.rowCount())}
    viper = rows["Viper 1-1 | Ace (player)"]
    assert viper[0] == "Aircraft F-16C_50" and viper[2] == "Viper 1-1"
    assert wait_until(qapp, lambda: "389 kt" in panel.table.item(0, 3).text() or "389 kt" in str(
        [panel.table.item(r, 3).text() for r in range(3)]), timeout=8)
    assert rows["Flanker 2-1"][0] == "Aircraft Su-27"
    assert any(r[0].startswith("Helicopter") for r in rows.values())


def test_kind_filter_and_units(qapp, app_rig) -> None:
    sim, link, window = app_rig(time_scale=4)
    panel = objects_tab(qapp, window)
    assert wait_until(qapp, lambda: panel.table.rowCount() == 3, timeout=8)
    panel.kind_checks["heli"].setChecked(False)
    assert panel.table.rowCount() == 2
    panel.unit_combo.setCurrentText("km/h")
    assert wait_until(qapp, lambda: any("km/h" in panel.table.item(r, 3).text() for r in range(2)), timeout=3)


def test_match_button_needs_a_selection(qapp, app_rig) -> None:
    sim, link, window = app_rig(time_scale=4)
    panel = objects_tab(qapp, window)
    assert wait_until(qapp, lambda: panel.table.rowCount() == 3, timeout=8)
    assert not panel.match_button.isEnabled()
    select(panel, "Hokum")
    assert panel.match_button.isEnabled() and not panel.cancel_button.isEnabled()


def test_match_camera_speed_while_playing(qapp, app_rig) -> None:
    sim, link, window = app_rig(time_scale=1)
    panel = objects_tab(qapp, window)
    assert wait_until(qapp, lambda: sim.t > 1.0 and panel.table.rowCount() == 3, timeout=8)
    select(panel, "Hokum")
    panel.match_button.click()
    assert wait_until(qapp, lambda: panel.cancel_button.isEnabled(), timeout=2)
    assert wait_until(qapp, lambda: not panel.cancel_button.isEnabled(), timeout=40)
    assert abs(sim.camv - 50.0) <= 1.0 and not sim.paused
    assert "matches Hokum 1-1" in panel.status.text()
    assert wait_until(qapp, lambda: sim.watched is None, timeout=2)  # watching stops
    assert "camera" in window.log_view.toPlainText()


def test_match_camera_speed_from_a_pause(qapp, app_rig) -> None:
    sim, link, window = app_rig(time_scale=1, paused=True, start=10.0)
    panel = objects_tab(qapp, window)
    window.speed.set_target(2)
    assert wait_until(qapp, lambda: sim.accel == 2 and panel.table.rowCount() == 3, timeout=8)
    select(panel, "Hokum")
    panel.match_button.click()
    assert wait_until(qapp, lambda: not sim.paused, timeout=5)  # runs, slowly
    assert sim.accel < 0.1
    assert wait_until(qapp, lambda: not panel.cancel_button.isEnabled() and sim.paused, timeout=60)
    assert abs(sim.camv - 50.0) <= 1.0
    assert wait_until(qapp, lambda: sim.accel == 2, timeout=10)  # the playback speed it had
    assert "matches Hokum 1-1" in panel.status.text()
