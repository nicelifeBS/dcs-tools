import ctypes
import sys

import pytest

from replay_helper.dcs.keys import INPUT, KEYBDINPUT, KeyPressError, Step, WindowsKeyBackend, key_events


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="layout checked for 64-bit")
def test_input_struct_matches_win64_layout() -> None:
    assert ctypes.sizeof(KEYBDINPUT) == 24
    assert ctypes.sizeof(INPUT) == 40


def test_key_events() -> None:
    # LCtrl down, Z down, Z up, LCtrl up -- the order DCS needs to see a chord
    assert key_events(Step.UP) == [(0x1D, False), (0x2C, False), (0x2C, True), (0x1D, True)]
    assert key_events(Step.DOWN)[0] == (0x38, False)
    assert key_events(Step.NORMAL)[-1] == (0x2A, True)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows error")
def test_windows_backend_refuses_elsewhere() -> None:
    with pytest.raises(KeyPressError, match="only work on Windows"):
        WindowsKeyBackend()
