"""Closed-loop time-acceleration control through keystrokes.

The controller presses one key at a time and waits until DCS's reported acceleration (STATE
accel=, from Export.LoGetModelTimeAcceleration) changes before pressing the next. A key DCS
did not see is retried; one it never sees fails loudly instead of leaving the speed unknown.

Only moves measured in DCS are used: "up" from 1x and above (+1x per step), "up" and "down"
below 1x (doubling / halving), and "normal" (back to 1x). Going down from above 1x is done as
"normal" then "up" -- what LAlt+Z does above 1x was never measured.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .keys import KeyBackend, LinkKeyBackend, Step, WindowsKeyBackend
from .protocol import State

EPS = 1e-3
SLOW_SPEEDS = (1 / 16, 1 / 8, 1 / 4, 1 / 2)
MAX_SPEED = 64
OVERSPEED_MARGIN = 1.2  # measured speed may lag and jitter; only act on a clear excess


def is_ladder_speed(x: float) -> bool:
    """Speeds DCS steps through: 1/16 .. 1/2 by halving, then 1, 2, 3, ... MAX_SPEED."""
    if any(abs(x - s) < EPS for s in SLOW_SPEEDS):
        return True
    return 1 - EPS <= x <= MAX_SPEED + EPS and abs(x - round(x)) < EPS


def next_step(accel: float, target: float) -> Step | None:
    """The next key towards `target` from `accel`, or None when there."""
    if abs(accel - target) < EPS:
        return None
    if target >= 1 - EPS:
        if accel < 1 - EPS or accel > target:
            return Step.NORMAL
        return Step.UP
    if accel > 1 + EPS:
        return Step.NORMAL
    if accel > target:
        return Step.DOWN
    return Step.UP


@dataclass
class _Pending:
    step: Step
    accel_before: float
    in_flight: bool = True  # the key is still being sent
    deadline: float = 0.0  # when sent: give up waiting for DCS to react at this time


class SpeedController(QObject):
    reached = Signal(float)
    failed = Signal(str)
    busyChanged = Signal(bool)
    stepped = Signal(object, float)  # (Step, accel before) -- for the UI log
    overspeed = Signal(float)  # paused because the replay ran faster than max_speed

    _pressDone = Signal(object)  # str error or None; may be emitted from the key thread

    CONFIRM_TIMEOUT_S = 1.0
    MAX_ATTEMPTS = 3  # per step
    MAX_STEPS = 2 * MAX_SPEED  # a whole climb from 1/16x to the top, with room to spare

    def __init__(self, link, backend: KeyBackend, *, clock: Callable[[], float] = time.monotonic,
                 tick_ms: int = 100, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._backend = backend
        self._clock = clock
        self._executor: ThreadPoolExecutor | None = None

        self._target: float | None = None
        self._pending: _Pending | None = None
        self._attempts = 0
        self._steps = 0
        self.max_speed: float | None = None
        self._overspeed_latched = False

        link.stateChanged.connect(self._on_state)
        self._pressDone.connect(self._on_press_done)
        self._timer = QTimer(self)
        self._timer.setInterval(tick_ms)
        self._timer.timeout.connect(self.tick)
        if tick_ms > 0:
            self._timer.start()

    # --- public -----------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._target is not None

    @property
    def target(self) -> float | None:
        return self._target

    def set_target(self, speed: float) -> None:
        if not is_ladder_speed(speed):
            raise ValueError(f"{speed}x is not a DCS speed step")
        was_busy = self.busy
        self._target = float(speed)
        self._attempts = 0
        self._steps = 0
        if not was_busy:
            self.busyChanged.emit(True)
        self._advance()

    def cancel(self) -> None:
        if self.busy:
            self._target = None
            self.busyChanged.emit(False)

    def tick(self) -> None:
        self._advance()

    def shutdown(self) -> None:
        self._timer.stop()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # --- internals --------------------------------------------------------------------
    def _on_state(self, s: State) -> None:
        self._check_overspeed(s)
        self._advance()

    def _check_overspeed(self, s: State) -> None:
        if s.paused:
            self._overspeed_latched = False
            return
        if self.max_speed is None or self._overspeed_latched:
            return
        too_fast_cmd = s.accel is not None and s.accel > self.max_speed + EPS
        too_fast_measured = s.speed is not None and s.speed > self.max_speed * OVERSPEED_MARGIN
        if too_fast_cmd or too_fast_measured:
            self._overspeed_latched = True
            self._link.pause()
            self.overspeed.emit(s.accel if too_fast_cmd else s.speed)
            self.set_target(self.max_speed)

    def _fail(self, message: str) -> None:
        self._target = None
        self._pending = None
        self.busyChanged.emit(False)
        self.failed.emit(message)

    def _advance(self) -> None:
        if self._target is None:
            return
        s = self._link.state
        if s is None or not self._link.connected:
            return
        if s.accel is None:
            self._fail("DCS does not report its time acceleration (is the hook up to date?)")
            return

        p = self._pending
        if p is not None:
            if p.in_flight:
                return
            if abs(s.accel - p.accel_before) > EPS:
                self._pending = None  # DCS reacted
                self._attempts = 0
            elif self._clock() >= p.deadline:
                self._pending = None
                self._attempts += 1
                if self._attempts >= self.MAX_ATTEMPTS:
                    self._fail(f"DCS did not react to {self.MAX_ATTEMPTS} speed keys ({p.step.name}); "
                               "is the DCS window open and not minimised?")
                    return
            else:
                return

        step = next_step(s.accel, self._target)
        if step is None:
            target, self._target = self._target, None
            self.busyChanged.emit(False)
            self.reached.emit(target)
            return
        if self._steps >= self.MAX_STEPS:
            self._fail(f"could not reach {self._target:g}x from {s.accel:g}x")
            return
        self._press(step, s.accel)

    def _press(self, step: Step, accel_before: float) -> None:
        self._steps += 1
        self._pending = _Pending(step, accel_before)
        self.stepped.emit(step, accel_before)
        if self._backend.blocking:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dcs-keys")
            self._executor.submit(self._run_press, step)
        else:
            self._run_press(step)

    def _run_press(self, step: Step) -> None:
        try:
            self._backend.press(step)
            error = None
        except Exception as exc:  # delivered to the UI thread as a failed attempt
            error = str(exc) or type(exc).__name__
        self._pressDone.emit(error)

    def _on_press_done(self, error: str | None) -> None:
        p = self._pending
        if p is None:
            return
        if error:
            self._pending = None
            self._attempts += 1
            if self._attempts >= self.MAX_ATTEMPTS:
                self._fail(f"could not send the speed key: {error}")
            return
        p.in_flight = False
        p.deadline = self._clock() + self.CONFIRM_TIMEOUT_S


class AutoKeyBackend:
    """Keystrokes for real DCS; KEY commands on the link when talking to tools/fake_dcs.py."""

    def __init__(self, link) -> None:
        self._link = link
        self._fake = LinkKeyBackend(link.send)
        self._windows: WindowsKeyBackend | None = None

    def _is_fake(self) -> bool:
        return (self._link.hook_version or "").startswith("fake")

    @property
    def blocking(self) -> bool:
        return not self._is_fake()

    def press(self, step: Step) -> None:
        if self._is_fake():
            self._fake.press(step)
            return
        if self._windows is None:
            self._windows = WindowsKeyBackend()
        self._windows.press(step)
