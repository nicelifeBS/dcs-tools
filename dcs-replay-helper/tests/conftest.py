from __future__ import annotations

import importlib.util
import os
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load_fake_dcs():
    """tools/fake_dcs.py is a script, not part of the package; import it by path."""
    if "fake_dcs" not in sys.modules:
        spec = importlib.util.spec_from_file_location("fake_dcs", TOOLS / "fake_dcs.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["fake_dcs"] = module
        spec.loader.exec_module(module)
    return sys.modules["fake_dcs"]


def _widgets_available() -> bool:
    try:
        from PySide6 import QtWidgets  # noqa: F401  (needs libEGL on Linux)
    except ImportError:
        return False
    return True


WIDGETS = _widgets_available()


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6.QtCore")
    if WIDGETS:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
    else:
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance() or QCoreApplication([])
    return app


def wait_until(qapp, condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_dcs_server() -> Iterator[Callable[..., tuple[object, int, int]]]:
    """Start tools/fake_dcs.py's simulator on free ports in a thread: (sim, state_port, cmd_port)."""
    fake = load_fake_dcs()
    stops: list[threading.Event] = []
    threads: list[threading.Thread] = []

    def start(time_scale: float = 1.0, **kwargs):
        sim = fake.FakeDcs(**kwargs)
        state_port, cmd_port = free_udp_port(), free_udp_port()
        stop, bound = threading.Event(), threading.Event()
        t = threading.Thread(
            target=fake.serve,
            kwargs=dict(sim=sim, fps=200, state_port=state_port, cmd_port=cmd_port,
                        should_stop=stop.is_set, quiet=True, time_scale=time_scale,
                        on_ready=bound.set),
            daemon=True,
        )
        t.start()
        assert bound.wait(5), "fake DCS did not start"
        stops.append(stop)
        threads.append(t)
        return sim, state_port, cmd_port

    yield start
    for stop in stops:
        stop.set()
    for t in threads:
        t.join(timeout=2)
