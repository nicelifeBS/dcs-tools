"""Match the free camera's speed (F11) to an object, from the keys and the wheel that set it.

DCS exposes no command or value for the free camera's speed (SPIKE.md round 8), so the app does
what a person does and measures the result. The hook (0.3.0) reports the camera's speed
(STATE cam=) and, for the WATCHed object, the speed the camera needs to keep up (tgt_along=):
the object's velocity on the camera's view axis, signed (negative: the camera flies backward).

What the keys and the wheel do, as measured:
  * LAlt+Num*  multiplies the speed by 1.1 per press (the first press from rest gives 5 m/s),
    LAlt+Num/ divides it by 1.1. Neither crosses zero.
  * The wheel adds 1.13 m/s per notch, crosses zero; wheel down is forward, wheel up backward.
  * Both are ignored while the replay is paused, and work in slow motion. A change ramps in over
    a second or two, so the speed is read only once it has settled.
So the keys do the coarse part and the wheel the last few m/s. Each round is one batch of
presses and one wait; the loop reads cam= again and repeats until it is within TOLERANCE.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from .keys import (INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MOUSEINPUT,
                   KeyPressError, WindowsKeyBackend, _INPUTUNION)
from .protocol import State

TOLERANCE = 1.0  # m/s: close enough (one wheel notch is 1.13)
KEY_FACTOR = 1.1  # per press
KEY_FIRST = 5.0  # m/s the first key press gives from rest
WHEEL_STEP = 1.13  # m/s per notch
KEY_MIN_ERR = 3.0  # below this error the wheel is finer than the keys
MAX_KEYS = 30  # presses per round
MAX_NOTCHES = 40  # notches per round
LEAVE_BACKWARD_TO = 4.0  # flying backward and needing forward: wheel up to about this, then keys
SLOW_ENOUGH = 8.0  # needing zero or backward while flying forward faster than this: keys slow it first

SLOW_SPEED = 1 / 16  # the replay speed used while matching from a pause (inputs are ignored paused)
SETTLE_MIN_S = 1.0  # after an input, wait at least this long (a speed change ramps in)
SETTLE_MAX_S = 6.0  # ... and no longer than this for it to stop changing
SETTLED_DELTA = 0.3  # m/s: cam= changing less than this between STATEs counts as steady
SETTLED_FOR_S = 0.4
CONFIRMS = 2  # evaluations in a row within tolerance before it counts as matched
MAX_ROUNDS = 30
RESUME_GRACE_S = 1.5  # after RESUME, STATE may say paused for a moment
NO_DATA_S = 6.0  # give up waiting for the camera or the object speed after this long


@dataclass(frozen=True)
class Action:
    kind: str  # faster | slower | wheel
    count: int  # key presses, or wheel notches (positive: the camera's speed goes forward)

    def describe(self) -> str:
        if self.kind == "wheel":
            return f"wheel {abs(self.count)} {'forward' if self.count > 0 else 'backward'}"
        return f"{self.count} x {'faster' if self.kind == 'faster' else 'slower'}"


def _keys_for_ratio(target: float, current: float) -> int:
    """Signed key presses that take `current` to `target`, both positive."""
    return round(math.log(target / current) / math.log(KEY_FACTOR))


def plan(target: float, current: float) -> Action | None:
    """The next input towards `target` m/s (signed) from `current`, or None when close enough."""
    err = target - current
    if abs(err) <= TOLERANCE:
        return None
    if target > 0 and current >= 0:
        if current < KEY_FIRST / 2:
            if target >= KEY_FIRST * 1.4:
                return Action("faster", 1)  # from rest the first press gives 5 m/s
        elif abs(err) > KEY_MIN_ERR:
            n = _keys_for_ratio(target, current)
            if n:
                n = max(-MAX_KEYS, min(MAX_KEYS, n))
                return Action("faster" if n > 0 else "slower", abs(n))
    elif current > SLOW_ENOUGH:
        n = max(-MAX_KEYS, _keys_for_ratio(LEAVE_BACKWARD_TO, current))
        return Action("slower", -n)
    elif target > 0 and current < 0:
        err = LEAVE_BACKWARD_TO - current
    notches = max(-MAX_NOTCHES, min(MAX_NOTCHES, round(err / WHEEL_STEP)))
    if notches == 0:
        notches = 1 if err > 0 else -1
    return Action("wheel", notches)


# --------------------------------------------------------------------------------------
# input backends
# --------------------------------------------------------------------------------------
class CameraInput(Protocol):
    blocking: bool  # True if the calls take long enough to need a worker thread

    def faster(self, presses: int) -> None: ...
    def slower(self, presses: int) -> None: ...
    def wheel(self, notches: int) -> None: ...  # positive: the camera's speed goes forward


class LinkCameraInput:
    """For tools/fake_dcs.py: the inputs are commands on the link."""

    blocking = False

    def __init__(self, send: Callable[[str], None]) -> None:
        self._send = send

    def faster(self, presses: int) -> None:
        self._send(f"CAM FASTER {presses}")

    def slower(self, presses: int) -> None:
        self._send(f"CAM SLOWER {presses}")

    def wheel(self, notches: int) -> None:
        self._send(f"CAM WHEEL {notches}")


SCAN_LALT, SCAN_NUM_MULTIPLY, SCAN_NUM_DIVIDE = 0x38, 0x37, 0x35
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_MOUSE, MOUSEEVENTF_WHEEL = 0, 0x0800
WHEEL_DELTA = 120  # one notch


def camera_key_events(faster: bool) -> list[tuple[int, bool, bool]]:
    """(scan code, key_up, extended) for LAlt+Num* (faster) or LAlt+Num/ (slower)."""
    key, extended = (SCAN_NUM_MULTIPLY, False) if faster else (SCAN_NUM_DIVIDE, True)
    return [(SCAN_LALT, False, False), (key, False, extended), (key, True, extended), (SCAN_LALT, True, False)]


def wheel_data(notches: int) -> int:
    """mouseData for a wheel move: positive is wheel up, sent as the DWORD two's complement."""
    return (notches * WHEEL_DELTA) & 0xFFFFFFFF


class WindowsCameraInput:
    """Keystrokes and wheel turns for the DCS window, through SendInput.

    The mouse wheel goes to the window under the cursor, so the cursor is moved onto the DCS
    window for the turns and put back. The window is brought to the front first.
    """

    blocking = True
    KEY_GAP_S = 0.05  # between presses
    WHEEL_GAP_S = 0.04  # between notches
    HOLD_S = 0.04  # between the events of one press

    def __init__(self) -> None:
        self._keys = WindowsKeyBackend()  # raises KeyPressError off Windows
        self._user32 = self._keys._user32

    def _send(self, kind: int, **union) -> None:
        inp = INPUT(type=kind, u=_INPUTUNION(**union))
        if self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise KeyPressError(f"SendInput failed (error {ctypes.get_last_error()})")

    def _press(self, faster: bool) -> None:
        for scan, key_up, extended in camera_key_events(faster):
            flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
            self._send(INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0))
            time.sleep(self.HOLD_S)

    def _keys_run(self, faster: bool, presses: int) -> None:
        self._keys.focus_dcs()
        for _ in range(presses):
            self._press(faster)
            time.sleep(self.KEY_GAP_S)

    def faster(self, presses: int) -> None:
        self._keys_run(True, presses)

    def slower(self, presses: int) -> None:
        self._keys_run(False, presses)

    def wheel(self, notches: int) -> None:
        from ctypes import wintypes

        u = self._user32
        hwnd = self._keys.focus_dcs()
        rect, old = wintypes.RECT(), wintypes.POINT()
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        u.GetCursorPos(ctypes.byref(old))
        u.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        try:
            # Forward is wheel down, backward is wheel up.
            step = -1 if notches > 0 else 1
            for _ in range(abs(notches)):
                self._send(INPUT_MOUSE, mi=MOUSEINPUT(0, 0, wheel_data(step), MOUSEEVENTF_WHEEL, 0, 0))
                time.sleep(self.WHEEL_GAP_S)
        finally:
            u.SetCursorPos(old.x, old.y)


class AutoCameraInput:
    """The real inputs on Windows; commands on the link for tools/fake_dcs.py."""

    def __init__(self, link) -> None:
        self._link = link
        self._fake = LinkCameraInput(link.send)
        self._windows: WindowsCameraInput | None = None

    def _backend(self) -> CameraInput:
        if (self._link.hook_version or "").startswith("fake"):
            return self._fake
        if self._windows is None:
            self._windows = WindowsCameraInput()
        return self._windows

    @property
    def blocking(self) -> bool:
        return not (self._link.hook_version or "").startswith("fake")

    def faster(self, presses: int) -> None:
        self._backend().faster(presses)

    def slower(self, presses: int) -> None:
        self._backend().slower(presses)

    def wheel(self, notches: int) -> None:
        self._backend().wheel(notches)


# --------------------------------------------------------------------------------------
# the controller
# --------------------------------------------------------------------------------------
class CameraMatcher(QObject):
    """Matches the free camera's speed to one object, then pauses again if it started paused."""

    progress = Signal(str)
    matched = Signal(str)
    failed = Signal(str)
    busyChanged = Signal(bool)

    _inputDone = Signal(object)  # str error or None; may be emitted from the input thread

    def __init__(self, link, speed, backend: CameraInput, *, clock: Callable[[], float] = time.monotonic,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._speed = speed
        self._backend = backend
        self._clock = clock
        self._executor: ThreadPoolExecutor | None = None

        self._obj: int | None = None
        self._label = ""
        self._phase = "idle"  # idle | slowing | wait | sending
        self._was_paused = False
        self._prev_accel: float | None = None
        self._started = 0.0
        self._settle_until = 0.0
        self._last_cam: float | None = None
        self._last_change = 0.0
        self._ok = 0
        self._rounds = 0
        self._last_watch = 0.0
        self._paused_ok_until = 0.0  # STATE still says paused for a moment after RESUME

        link.stateChanged.connect(self._on_state)
        self._inputDone.connect(self._on_input_done)
        if speed is not None:
            speed.reached.connect(self._on_slow_reached)
            speed.failed.connect(self._on_slow_failed)

    # --- public -----------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._obj is not None

    def start(self, dcs_id: int, label: str = "") -> None:
        """Match the camera's speed to object `dcs_id`."""
        if self.busy:
            self._abort("cancelled")
        s = self._link.state
        if s is None or not self._link.connected:
            self.failed.emit("DCS is not connected")
            return
        if not self._link.reports_objects:
            self.failed.emit("the DCS hook is too old to report the camera speed: Tools > Install / update DCS hook")
            return
        self._obj, self._label = dcs_id, label or str(dcs_id)
        self._was_paused, self._prev_accel = s.paused, s.accel
        self._rounds, self._ok = 0, 0
        self._last_cam, self._started = None, self._clock()
        self._last_change = self._started
        self._settle_until = self._started
        self.busyChanged.emit(True)
        self._link.watch(dcs_id)
        self._last_watch = self._started
        if s.paused:
            # Keys and wheel are ignored while paused: run at the slowest speed meanwhile.
            if self._speed is None:
                self._finish_fail("the camera can not be changed while the replay is paused")
                return
            self.progress.emit("replay paused: running in slow motion while the camera speed is set")
            self._phase = "slowing"
            self._speed.set_target(SLOW_SPEED)
        else:
            self._phase = "wait"

    def cancel(self) -> None:
        if self.busy:
            self._abort("cancelled")

    def shutdown(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # --- internals --------------------------------------------------------------------
    def _on_slow_reached(self, _speed: float) -> None:
        if self._phase != "slowing":
            return
        self._link.resume()
        self._phase = "wait"
        self._paused_ok_until = self._clock() + RESUME_GRACE_S
        self._settle_until = self._clock() + SETTLE_MIN_S

    def _on_slow_failed(self, message: str) -> None:
        if self._phase == "slowing":
            self._finish_fail(f"could not slow the replay down: {message}")

    def _on_state(self, s: State) -> None:
        if self._phase != "wait" or self._obj is None:
            return
        now = self._clock()
        if s.paused and now >= self._paused_ok_until:
            self._finish_fail("the replay was paused")
            return
        if s.tgt != self._obj and now - self._last_watch >= 1.0:
            self._link.watch(self._obj)
            self._last_watch = now
        if s.paused:
            return
        if s.cam is None or s.tgt != self._obj or s.tgt_along is None:
            if now - self._started > NO_DATA_S:
                if s.cam is None:
                    self._finish_fail("DCS does not report the camera: is the free camera (F11) active?")
                else:
                    self._finish_fail("the object's speed is not known: it needs to move for a moment. "
                                      "Let the replay play and try again")
            return
        if self._last_cam is None or abs(s.cam - self._last_cam) > SETTLED_DELTA:
            self._last_change = now
        self._last_cam = s.cam
        steady = now - self._last_change >= SETTLED_FOR_S
        if now < self._settle_until or not (steady or now >= self._settle_until + SETTLE_MAX_S - SETTLE_MIN_S):
            return

        action = plan(s.tgt_along, s.cam)
        if action is None:
            self._ok += 1
            if self._ok >= CONFIRMS:
                self._finish_ok(s)
            else:
                self._settle_until = now + SETTLED_FOR_S
            return
        self._ok = 0
        if self._rounds >= MAX_ROUNDS:
            self._finish_fail(f"gave up after {MAX_ROUNDS} rounds: camera {s.cam:.1f} m/s, "
                              f"object {s.tgt_along:.1f} m/s")
            return
        self._rounds += 1
        self.progress.emit(f"camera {s.cam:.1f} m/s, {self._label} {s.tgt_along:.1f} m/s: {action.describe()}")
        self._phase = "sending"
        if self._backend.blocking:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dcs-camera")
            self._executor.submit(self._run_input, action)
        else:
            self._run_input(action)

    def _run_input(self, action: Action) -> None:
        try:
            if action.kind == "faster":
                self._backend.faster(action.count)
            elif action.kind == "slower":
                self._backend.slower(action.count)
            else:
                self._backend.wheel(action.count)
            error = None
        except Exception as exc:  # delivered to the UI thread
            error = str(exc) or type(exc).__name__
        self._inputDone.emit(error)

    def _on_input_done(self, error: str | None) -> None:
        if self._phase != "sending":
            return
        if error:
            self._finish_fail(f"could not send the camera input: {error}")
            return
        now = self._clock()
        self._phase = "wait"
        self._settle_until = now + SETTLE_MIN_S
        self._last_change = now

    def _restore(self) -> None:
        """Back to what it was: watching stopped, paused again at the playback speed."""
        self._link.watch(None)
        self._phase = "idle"
        self._obj = None
        if self._was_paused:
            self._link.pause()
            if self._speed is not None and self._prev_accel is not None:
                try:
                    self._speed.set_target(self._prev_accel)
                except ValueError:
                    pass
        self.busyChanged.emit(False)

    def _finish_ok(self, s: State) -> None:
        label = self._label
        side = s.tgt_side
        text = f"camera speed {s.cam:.1f} m/s matches {label} ({s.tgt_along:.1f} m/s along the view)"
        if side is not None and side > 5:
            text += f"; it also moves {side:.0f} m/s across the view, which the camera cannot follow"
        self._restore()
        self.matched.emit(text)

    def _finish_fail(self, message: str) -> None:
        self._restore()
        self.failed.emit(message)

    def _abort(self, message: str) -> None:
        if self._speed is not None and self._phase == "slowing":
            self._speed.cancel()
        self._finish_fail(message)
