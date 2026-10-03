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
