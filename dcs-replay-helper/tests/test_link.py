"""DcsLink against tools/fake_dcs.py over real localhost UDP."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtNetwork")

from conftest import free_udp_port, wait_until  # noqa: E402
from replay_helper.dcs.link import DcsLink  # noqa: E402
from replay_helper.dcs.protocol import Arrived, Disarmed, Error  # noqa: E402


@pytest.fixture
def connect(qapp, fake_dcs_server):
    links = []

    def make(**sim_kwargs):
        sim, state_port, cmd_port = fake_dcs_server(**sim_kwargs)
        link = DcsLink(state_port=state_port, cmd_port=cmd_port)
        assert link.start()
        links.append(link)
        assert wait_until(qapp, lambda: link.connected and link.hook_version), "no reply from fake DCS"
        return sim, link

    yield make
    for link in links:
        link.stop()


def collect(link: DcsLink) -> list:
    got = []
    link.message.connect(got.append)
    return got


def test_connects_and_reads_state(qapp, connect) -> None:
    sim, link = connect(start=10.0)
    assert link.hook_version == "fake-0.1.0"
    assert link.state.start_tod == 59400 and link.state.theatre == "Caucasus"
    assert wait_until(qapp, lambda: link.state.t > 10.1)


def test_pause_and_resume(qapp, connect) -> None:
    sim, link = connect()
    link.pause()
    assert wait_until(qapp, lambda: link.state.paused)
    t = link.model_time_now()
    qapp.processEvents()
    assert link.model_time_now() == t  # a paused clock does not extrapolate
    link.resume()
    assert wait_until(qapp, lambda: not link.state.paused)


def test_armed_stop_arrives(qapp, connect) -> None:
    sim, link = connect()
    got = collect(link)
    sim.handle("KEY UP")
    sim.handle("KEY UP")
    sim.handle("KEY UP")
    link.arm_stop(1.0)
    assert wait_until(qapp, lambda: any(isinstance(m, Arrived) for m in got))
    arrived = next(m for m in got if isinstance(m, Arrived))
    assert arrived.target == 1.0 and arrived.over >= 0
    assert wait_until(qapp, lambda: link.state.paused and link.state.stop is None)


def test_forward_only_error_and_disarm(qapp, connect) -> None:
    sim, link = connect(start=50.0)
    got = collect(link)
    link.arm_stop(10.0)
    assert wait_until(qapp, lambda: any(isinstance(m, Error) for m in got))
    link.arm_stop(500.0)
    assert wait_until(qapp, lambda: link.state.stop == 500.0)
    link.disarm()
    assert wait_until(qapp, lambda: any(isinstance(m, Disarmed) for m in got))
    assert wait_until(qapp, lambda: link.state.stop is None)


def test_clock_never_extrapolates_past_armed_stop(qapp, connect) -> None:
    sim, link = connect()
    link.arm_stop(0.4)
    assert wait_until(qapp, lambda: link.state.stop == 0.4 or link.state.paused)
    for _ in range(50):
        t = link.model_time_now()
        assert t <= 0.4 + 1e-9 or link.state.paused
        qapp.processEvents()


def test_disconnect_after_timeout(qapp, fake_dcs_server) -> None:
    sim, state_port, cmd_port = fake_dcs_server()
    now = [0.0]
    link = DcsLink(state_port=state_port, cmd_port=cmd_port, timeout_s=2.0, clock=lambda: now[0])
    changes = []
    link.connectedChanged.connect(changes.append)
    assert link.start()
    assert wait_until(qapp, lambda: link.connected)
    link.stop()  # no more packets
    now[0] = 3.0
    link._check_alive()
    assert changes == [True, False]


def test_bind_conflict_is_reported(qapp) -> None:
    port = free_udp_port()
    first = DcsLink(state_port=port)
    assert first.start()
    second = DcsLink(state_port=port)
    assert not second.start()
    assert second.bind_error()
    first.stop()


def test_asks_for_hook_version_until_known(qapp, fake_dcs_server) -> None:
    from replay_helper.dcs.protocol import Hello, Pong

    sim, state_port, cmd_port = fake_dcs_server()
    link = DcsLink(state_port=state_port, cmd_port=cmd_port)
    real_handle, lost = link._handle, [True]

    def handle(msg):  # HELLO and the first PONGs never arrive
        if lost[0] and isinstance(msg, (Hello, Pong)):
            return
        real_handle(msg)

    link._handle = handle
    sent = []
    real_send = link.send
    link.send = lambda line: (sent.append(line), real_send(line))
    assert link.start()
    assert wait_until(qapp, lambda: link.connected)
    assert wait_until(qapp, lambda: sent.count("PING") >= 2, timeout=3)  # asked again
    assert link.hook_version is None
    lost[0] = False
    assert wait_until(qapp, lambda: link.hook_version == "fake-0.1.0", timeout=3)
    pings = sent.count("PING")
    wait_until(qapp, lambda: False, timeout=1.5)
    assert sent.count("PING") == pings  # stops asking once known
    link.stop()
