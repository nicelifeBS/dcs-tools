"""Time-acceleration keystrokes for DCS.

DCS gives Lua no way to set time acceleration (the iCommand ids are not reachable from any
Lua state, see SPIKE.md), so the app presses DCS's own keys: LCtrl+Z (up), LAlt+Z (down),
LShift+Z (back to 1x). DCS reads input through DirectInput, so they are sent as scan codes,
and only to the focused DCS window.

Measured in DCS: above 1x each "up" adds 1x (1, 2, 3, 4, ...); below 1x the steps halve
(1, 0.5, 0.25); keys pressed while paused take effect at once, and
Export.LoGetModelTimeAcceleration (STATE accel=) reports the result immediately.
"""

from __future__ import annotations

import ctypes
import sys
import time
from enum import Enum
from typing import Protocol


class Step(Enum):
    UP = "UP"  # LCtrl+Z
    DOWN = "DOWN"  # LAlt+Z
    NORMAL = "NORMAL"  # LShift+Z


class KeyPressError(RuntimeError):
    """A keystroke could not be delivered (no DCS window, focus refused, SendInput failed)."""


class KeyBackend(Protocol):
    blocking: bool  # True if press() takes long enough to need a worker thread

    def press(self, step: Step) -> None: ...


# --------------------------------------------------------------------------------------
# fake DCS: the "keys" are commands on the link
# --------------------------------------------------------------------------------------
class LinkKeyBackend:
    """For tools/fake_dcs.py, which takes KEY UP|DOWN|NORMAL instead of keystrokes."""

    blocking = False

    def __init__(self, send) -> None:
        self._send = send

    def press(self, step: Step) -> None:
        self._send(f"KEY {step.value}")


# --------------------------------------------------------------------------------------
# real DCS on Windows: SendInput scan codes to the DCS window
# --------------------------------------------------------------------------------------
SCAN_LCTRL, SCAN_LALT, SCAN_LSHIFT, SCAN_Z = 0x1D, 0x38, 0x2A, 0x2C
MODIFIER = {Step.UP: SCAN_LCTRL, Step.DOWN: SCAN_LALT, Step.NORMAL: SCAN_LSHIFT}
DCS_WINDOW_TITLE = "Digital Combat Simulator"

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
VK_MENU = 0x12

# Explicit widths rather than ctypes.wintypes, whose DWORD is 8 bytes off Windows: the
# layout is then the same everywhere and can be checked by tests on any 64-bit machine.
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):  # largest union member; it sets sizeof(INPUT)
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


def key_events(step: Step) -> list[tuple[int, bool]]:
    """(scan code, key_up) in press order: modifier down, Z down, Z up, modifier up."""
    mod = MODIFIER[step]
    return [(mod, False), (SCAN_Z, False), (SCAN_Z, True), (mod, True)]


class WindowsKeyBackend:
    """Focuses the DCS window and presses the step's key combination."""

    blocking = True
    FOCUS_SETTLE_S = 0.08  # let Windows hand over focus before the first key
    HOLD_S = 0.06  # between key events: long enough for DCS to see the key on a frame

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise KeyPressError("keystrokes to DCS only work on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def _find_window(self) -> int:
        return self._user32.FindWindowW(None, DCS_WINDOW_TITLE)

    def _focus(self, hwnd: int) -> None:
        u = self._user32
        if u.GetForegroundWindow() == hwnd:
            return
        if not u.SetForegroundWindow(hwnd):
            # Windows only lets the foreground process hand over focus. A synthetic Alt tap
            # makes this process count as having had input; DCS is not focused yet, so it
            # never sees the Alt.
            u.keybd_event(VK_MENU, 0, 0, 0)
            u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            u.SetForegroundWindow(hwnd)
        time.sleep(self.FOCUS_SETTLE_S)
        if u.GetForegroundWindow() != hwnd:
            raise KeyPressError("Windows refused to bring the DCS window to the front")

    def press(self, step: Step) -> None:
        hwnd = self._find_window()
        if not hwnd:
            raise KeyPressError(f"no window titled '{DCS_WINDOW_TITLE}'")
        self._focus(hwnd)
        for scan, key_up in key_events(step):
            flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
            inp = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
            if self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
                raise KeyPressError(f"SendInput failed (error {ctypes.get_last_error()})")
            time.sleep(self.HOLD_S)
