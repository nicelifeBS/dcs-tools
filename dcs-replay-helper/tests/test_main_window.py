"""Headless runs of the main window against the fake DCS."""

from __future__ import annotations

import pytest

from conftest import WIDGETS, wait_until

pytestmark = pytest.mark.skipif(not WIDGETS, reason="Qt widgets unavailable (libEGL missing)")


@pytest.fixture
def app_rig(qapp, fake_dcs_server):
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
        window = MainWindow(link, speed, seek)
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
    assert "Connected to DCS (hook fake-0.1.0)" in window.conn_label.text()
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
    assert log.count("speed key LCtrl+Z") == 3

    window.limit_combo.setCurrentIndex(window.limit_combo.findData(2))
    window.play_button.click()  # runs at 4x, above the new 2x limit -> paused, back to 2x
    assert wait_until(qapp, lambda: sim.accel == 2 and sim.paused)
    assert "above the 2x limit: paused" in window.log_view.toPlainText()


def test_window_seek_with_pre_and_post_roll(qapp, app_rig) -> None:
    sim, link, window = app_rig(start=50.0, time_scale=10)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)

    window.goto_edit.setText("16:32:00")  # mission time = replay 2:00
    window.goto_mode.setCurrentIndex(window.goto_mode.findData("mission"))
    window.preroll_spin.setValue(5)
    window.postroll_spin.setValue(3)
    window.go_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Ready"), timeout=10), \
        window.seek_status.text()
    assert window.seek_status.text() == ("Ready: paused at 1:55.0, 5 s before the target at 2:00.0. "
                                         "Play runs through it and pauses 3 s after.")
    assert 115.0 <= sim.t < 115.5 and sim.paused and sim.accel == 1 and sim.max_running_accel == 4
    assert window.play_button.text() == "Play through (pauses 3 s after the target)"

    window.play_button.click()
    assert wait_until(qapp, lambda: window.seek_status.text().startswith("Paused at"), timeout=10)
    assert window.seek_status.text() == "Paused at 2:03.0, 3.0 s after the target."
    assert 123.0 <= sim.t < 123.5 and sim.paused
    assert wait_until(qapp, lambda: window.play_button.text() == "Play")  # on the next STATE


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
