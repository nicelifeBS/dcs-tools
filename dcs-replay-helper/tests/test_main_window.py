"""Headless smoke test of the main window against the fake DCS."""

from __future__ import annotations

import pytest

from conftest import WIDGETS, wait_until

pytestmark = pytest.mark.skipif(not WIDGETS, reason="Qt widgets unavailable (libEGL missing)")


def test_window_follows_dcs(qapp, fake_dcs_server) -> None:
    from replay_helper.dcs.link import DcsLink
    from replay_helper.ui.main_window import MainWindow

    sim, state_port, cmd_port = fake_dcs_server(start=62.95, paused=True)
    link = DcsLink(state_port=state_port, cmd_port=cmd_port)
    assert link.start()
    window = MainWindow(link)
    assert "Waiting for DCS" in window.conn_label.text()
    assert not window.play_button.isEnabled()

    assert wait_until(qapp, lambda: link.connected)
    window.refresh()
    assert "Connected to DCS (hook fake-0.1.0)" in window.conn_label.text()
    assert window.clock_label.text() == "1:03.0"
    assert window.tod_label.text() == "Mission time 16:31:02"
    assert window.play_button.text() == "Play"
    assert window.mission_label.text() == "Caucasus  2018-02-01"

    window.play_button.click()
    assert wait_until(qapp, lambda: not link.state.paused)
    assert wait_until(qapp, lambda: window.play_button.text() == "Pause")

    window.stop_spin.setValue(link.state.t + 0.3)
    window.arm_button.click()
    assert wait_until(qapp, lambda: link.state.paused, timeout=3)
    assert wait_until(qapp, lambda: window.stop_label.text().startswith("Stopped at"))
    assert "arrived" in window.log_view.toPlainText()
    link.stop()
    window.close()


def test_window_sets_speed_within_limit(qapp, fake_dcs_server) -> None:
    from replay_helper.dcs.link import DcsLink
    from replay_helper.dcs.speed import AutoKeyBackend, SpeedController
    from replay_helper.ui.main_window import MainWindow

    sim, state_port, cmd_port = fake_dcs_server(paused=True)
    link = DcsLink(state_port=state_port, cmd_port=cmd_port)
    assert link.start()
    speed = SpeedController(link, AutoKeyBackend(link))
    window = MainWindow(link, speed)
    assert wait_until(qapp, lambda: link.connected and link.hook_version)

    window.speed_combo.setCurrentIndex(window.speed_combo.findData(8))  # above the default 4x limit
    window.speed_button.click()
    assert wait_until(qapp, lambda: window.speed_status.text() == "Speed set to 4x")
    assert sim.accel == 4
    log = window.log_view.toPlainText()
    assert "8x is above the limit; using 4x" in log
    assert log.count("speed key LCtrl+Z") == 3

    window.limit_combo.setCurrentIndex(window.limit_combo.findData(2))
    window.play_button.click()  # runs at 4x, above the new 2x limit -> paused, back to 2x
    assert wait_until(qapp, lambda: sim.accel == 2 and sim.paused)
    assert "above the 2x limit: paused" in window.log_view.toPlainText()
    speed.shutdown()
    link.stop()
    window.close()
