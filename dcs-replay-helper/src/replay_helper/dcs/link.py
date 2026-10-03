"""Qt UDP link to hook/ReplayHelper.lua."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

from . import protocol
from .protocol import Hello, Message, Pong, State

# Never extrapolate the clock further than this past the last STATE: if packets stop, the
# display should freeze, not run away.
MAX_EXTRAPOLATION_S = 0.5


class DcsLink(QObject):
    """Receives STATE and replies from the hook, sends commands to it.

    `connected` means a STATE arrived within the last `timeout_s` seconds.
    """

    stateChanged = Signal(object)  # protocol.State
    message = Signal(object)  # every other protocol message
    connectedChanged = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        host: str = protocol.HOST,
        state_port: int = protocol.STATE_PORT,
        cmd_port: int = protocol.CMD_PORT,
        timeout_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._host = QHostAddress(host)
        self._state_port = state_port
        self._cmd_port = cmd_port
        self._timeout_s = timeout_s
        self._clock = clock

        self._sock = QUdpSocket(self)
        self._sock.readyRead.connect(self._read)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self._check_alive)

        self._state: State | None = None
        self._state_at = 0.0
        self._connected = False
        self.hook_version: str | None = None

    # --- lifecycle --------------------------------------------------------------------
    def start(self) -> bool:
        """Bind the state port. False if it is taken (another copy, or the spike client)."""
        if not self._sock.bind(self._host, self._state_port):
            return False
        self._watchdog.start()
        self.send(protocol.cmd_ping())
        return True

    def bind_error(self) -> str:
        return self._sock.errorString()

    def stop(self) -> None:
        self._watchdog.stop()
        if self._sock.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._sock.close()

    # --- commands ---------------------------------------------------------------------
    def send(self, line: str) -> None:
        self._sock.writeDatagram(line.encode("utf-8"), self._host, self._cmd_port)

    def pause(self) -> None:
        self.send(protocol.cmd_pause())

    def resume(self) -> None:
        self.send(protocol.cmd_resume())

    def arm_stop(self, t: float) -> None:
        self.send(protocol.cmd_armstop(t))

    def disarm(self) -> None:
        self.send(protocol.cmd_disarm())

    # --- state ------------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def state(self) -> State | None:
        return self._state

    def model_time_now(self) -> float | None:
        """Model time now, extrapolated from the last STATE for a smooth display."""
        s = self._state
        if s is None:
            return None
        if s.paused:
            return s.t
        rate = s.accel if s.accel is not None else s.speed
        if rate is None:
            rate = 1.0
        dt = min(max(self._clock() - self._state_at, 0.0), MAX_EXTRAPOLATION_S)
        t = s.t + dt * rate
        if s.stop is not None:
            t = min(t, s.stop)  # the hook pauses there; don't show the clock past it
        return t

    # --- internals --------------------------------------------------------------------
    def _read(self) -> None:
        while self._sock.hasPendingDatagrams():
            datagram = self._sock.receiveDatagram()
            line = bytes(datagram.data()).decode("utf-8", errors="replace")
            self._handle(protocol.parse(line))

    def _handle(self, msg: Message | None) -> None:
        if msg is None:
            return
        if isinstance(msg, State):
            self._state = msg
            self._state_at = self._clock()
            self._set_connected(True)
            self.stateChanged.emit(msg)
            return
        if isinstance(msg, (Hello, Pong)):
            self.hook_version = msg.version
        self.message.emit(msg)

    def _check_alive(self) -> None:
        if self._connected and self._clock() - self._state_at > self._timeout_s:
            self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            self.connectedChanged.emit(value)
