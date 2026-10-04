"""Console client for the milestone 0 spike hook (hook/spike/ReplayHelperSpike.lua).

Standard library only, so it runs with any Python 3.10+ on the DCS machine:

    python spike_client.py

It listens for the hook's packets on 127.0.0.1:47810, sends commands to 127.0.0.1:47811,
and writes everything to spike_session.log in the current directory so the session can be
shared afterwards. Type `help` at the prompt for the command list.
"""

from __future__ import annotations

import re
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HOST = "127.0.0.1"
STATE_PORT = 47810  # hook -> client
CMD_PORT = 47811  # client -> hook
LOG_STATE_EVERY = 1.0  # seconds between STATE lines copied into the session log

HELP = """\
commands (case-insensitive):
  s                      show the last STATE
  w                      toggle printing STATE once a second
  p | r                  pause | resume
  arm <t> | disarm       arm / clear a stop at model time t
  probe                  report reachable APIs (results print as they arrive)
  find [subdir]          search the DCS install for time-acceleration command ids
  cmd <id> [value]       LoSetCommand from the hooks state
  cmdx <id> [value]      LoSetCommand inside the export state
  digital <id> [value]   DCS.dispatchDigitalAction
  globals [words]        list globals named like the words (default: accel decel) in each
                         Lua state -- this is where the iCommand ids come from
  cam                    the camera and the unit it is aimed at (round 4)
  objects [all]          aircraft (or all units) with their DCS ids
  view [route] <id> [value]
                         send a view command (8 = F2, 181 = next, 180 = previous), then show
                         where the camera went. route: digital (default, dispatchDigitalAction),
                         export (LoSetCommand in the export state) or hooks (does nothing in a replay)
  focus <unit> [route] [prev]
                         F2, then next (or previous) object until the camera is on the unit: a
                         DCS id (decimal or 0x hex, as in `objects`) or part of its unit/group
                         name. `focus` alone cancels
  key f1|f2|ctrl+f2|... [count] [delay]
                         Windows only: press a view key in DCS, then show `cam`
  kfocus <id> [key] [max]
                         Windows only: `focus` with keystrokes -- press the key (default f2)
                         until `cam` says the unit (DCS id, decimal or 0x hex) is in view
  key up|down|normal [count] [delay]
                         Windows only: send LCtrl+Z / LAlt+Z / LShift+Z to the DCS window.
                         delay (default 3 s) gives you time to click into DCS if focusing fails;
                         the STATE line (with accel=) is shown about a second afterwards
  raw <line>             send a raw command line
  q                      quit
"""


class SessionLog:
    def __init__(self, path: Path) -> None:
        self._fh = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self.write(f"--- session start {datetime.now().isoformat(timespec='seconds')} ---")

    def write(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with self._lock:
            self._fh.write(f"{stamp} {line}\n")
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class Client:
    def __init__(self, log: SessionLog) -> None:
        self.log = log
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind((HOST, STATE_PORT))
        self.rx.settimeout(0.5)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_state: str | None = None
        self.last_state_at = 0.0
        self.watch = False
        self.running = True
        self._last_logged_state = 0.0
        self._expect_prefix: str | None = None  # wait_for(): the next line starting with this
        self._expect_line: str | None = None
        self._expect_event = threading.Event()

    def send(self, line: str) -> None:
        self.tx.sendto(line.encode("utf-8"), (HOST, CMD_PORT))
        self.log.write(f">> {line}")

    def receive_loop(self) -> None:
        while self.running:
            try:
                data, _ = self.rx.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            line = data.decode("utf-8", errors="replace").strip()
            now = time.monotonic()
            if line.startswith("STATE "):
                self.last_state = line
                self.last_state_at = now
                if now - self._last_logged_state >= LOG_STATE_EVERY:
                    self._last_logged_state = now
                    self.log.write(f"<< {line}")
                    if self.watch:
                        print(f"  {line}")
            else:
                self.log.write(f"<< {line}")
                print(f"  {line}")
                if self._expect_prefix and line.startswith(self._expect_prefix):
                    self._expect_prefix = None
                    self._expect_line = line
                    self._expect_event.set()

    def request(self, line: str, reply_prefix: str, timeout: float = 2.0) -> str | None:
        """Send a command and return the first reply line starting with reply_prefix."""
        self._expect_event.clear()
        self._expect_line = None
        self._expect_prefix = reply_prefix
        self.send(line)
        self._expect_event.wait(timeout)
        self._expect_prefix = None
        return self._expect_line

    def show_state(self) -> None:
        if not self.last_state:
            print("  no STATE received yet -- is a mission or track running with the hook installed?")
            return
        age = time.monotonic() - self.last_state_at
        print(f"  {self.last_state}  ({age:.1f}s ago)")


# --------------------------------------------------------------------------------------
# Windows keystroke injection (fallback speed control)
# --------------------------------------------------------------------------------------
SCAN_LCTRL, SCAN_LALT, SCAN_LSHIFT, SCAN_Z = 0x1D, 0x38, 0x2A, 0x2C
SPEED_KEYS = {"up": SCAN_LCTRL, "down": SCAN_LALT, "normal": SCAN_LSHIFT}
MODIFIER_SCANS = {"ctrl": SCAN_LCTRL, "alt": SCAN_LALT, "shift": SCAN_LSHIFT}
FKEY_SCANS = {f"f{n}": 0x3A + n for n in range(1, 11)} | {"f11": 0x57, "f12": 0x58}


def view_chord(name: str) -> list[int] | None:
    """Scan codes for a view key such as f2 or ctrl+f2 (left-hand modifiers); None if unknown."""
    *mods, key = name.lower().split("+")
    if key not in FKEY_SCANS or any(m not in MODIFIER_SCANS for m in mods):
        return None
    return [MODIFIER_SCANS[m] for m in mods] + [FKEY_SCANS[key]]


def _press_chord(scans: list[int]) -> None:
    _send_scancodes([(s, False) for s in scans] + [(s, True) for s in reversed(scans)])


def _send_scancodes(sequence: list[tuple[int, bool]]) -> None:
    """Send (scan code, key_up) pairs with SendInput. DCS reads DirectInput, so scan codes."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 0x0002, 0x0008

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):  # largest union member; sets sizeof(INPUT)
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    for scan, key_up in sequence:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
        inp = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise OSError(f"SendInput failed (error {ctypes.get_last_error()})")
        time.sleep(0.05)  # hold long enough for DCS to see it on at least one frame


def _focus_dcs() -> bool:
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = user32.FindWindowW(None, "Digital Combat Simulator")
    if not hwnd:
        hwnd = user32.FindWindowW("DCS", None)
    if not hwnd:
        return False
    return bool(user32.SetForegroundWindow(hwnd))


def press_speed_key(which: str, count: int, delay: float, client: Client) -> None:
    if sys.platform != "win32":
        print("  key injection only works on Windows")
        return
    modifier = SPEED_KEYS[which]
    focused = _focus_dcs()
    print(f"  DCS window focus: {'ok' if focused else 'FAILED -- click into DCS now'}; sending in {delay:.0f}s")
    time.sleep(delay)
    for _ in range(count):
        _send_scancodes([(modifier, False), (SCAN_Z, False), (SCAN_Z, True), (modifier, True)])
        time.sleep(0.6)  # leave a speed sample window between steps
    client.log.write(f"## key {which} x{count} (focus {'ok' if focused else 'failed'})")
    print(f"  sent {which} x{count}")
    time.sleep(1.0)  # let the hook report the new rate
    client.show_state()


def press_view_key(name: str, count: int, delay: float, client: Client) -> None:
    if sys.platform != "win32":
        print("  key injection only works on Windows")
        return
    focused = _focus_dcs()
    print(f"  DCS window focus: {'ok' if focused else 'FAILED -- click into DCS now'}; sending in {delay:.0f}s")
    time.sleep(delay)
    for _ in range(count):
        _press_chord(view_chord(name))
        time.sleep(0.3)
    client.log.write(f"## key {name} x{count} (focus {'ok' if focused else 'failed'})")
    print(f"  sent {name} x{count}")
    time.sleep(0.3)
    client.send("CAM")


AIMED_ID = re.compile(r"\baimed id=(\d+)/")


def parse_unit_id(text: str) -> int | None:
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def key_focus(target: int, chord: str, max_steps: int, delay: float, client: Client) -> None:
    """FOCUS done with keystrokes: press the view key until CAM says the target is in view."""
    if sys.platform != "win32":
        print("  key injection only works on Windows")
        return
    focused = _focus_dcs()
    print(f"  DCS window focus: {'ok' if focused else 'FAILED -- click into DCS now'}; starting in {delay:.0f}s")
    time.sleep(delay)
    started = time.monotonic()
    visited: list[str] = []
    result = "fail reason=max_steps"
    for step in range(max_steps + 1):
        if step:
            _press_chord(view_chord(chord))
            time.sleep(0.3)  # for the camera to move
        reply = client.request("CAM", "CAM aimed")
        match = AIMED_ID.search(reply or "")
        if not match:
            result = "fail reason=no_CAM_reply" if reply is None else "fail reason=nothing_aimed"
            if reply is None:
                break
            visited.append("none")
            continue
        unit = int(match.group(1))
        if unit == target:
            result = "ok"
            break
        if visited and f"0x{unit:x}" == visited[0]:
            result = "fail reason=cycled"
            break
        visited.append(f"0x{unit:x}")
    line = (f"KFOCUS-DONE {result} target=0x{target:x} key={chord} presses={step} "
            f"time={time.monotonic() - started:.1f} visited={','.join(visited) or '-'}")
    client.log.write(f"## {line}")
    print(f"  {line}")


# --------------------------------------------------------------------------------------
# REPL
# --------------------------------------------------------------------------------------
def handle(client: Client, text: str) -> bool:
    parts = text.split()
    if not parts:
        return True
    word, args = parts[0].lower(), parts[1:]

    simple = {"p": "PAUSE", "r": "RESUME", "disarm": "DISARM", "probe": "PROBE", "ping": "PING"}
    if word in ("q", "quit", "exit"):
        return False
    if word in ("h", "help", "?"):
        print(HELP)
    elif word == "s":
        client.show_state()
    elif word == "w":
        client.watch = not client.watch
        print(f"  watch {'on' if client.watch else 'off'}")
    elif word in simple:
        client.send(simple[word])
    elif word == "arm" and len(args) == 1:
        client.send(f"ARM {args[0]}")
    elif word == "find":
        client.send("FINDCMDS " + " ".join(args))
    elif word in ("cmd", "cmdx", "digital") and 1 <= len(args) <= 2:
        prefix = {"cmd": "LOCMD", "cmdx": "LOCMDX", "digital": "DIGITAL"}[word]
        client.send(f"{prefix} " + " ".join(args))
    elif word == "globals":
        client.send("GLOBALS " + " ".join(args))
    elif word == "cam":
        client.send("CAM")
    elif word == "objects" and len(args) <= 1:
        client.send("OBJECTS " + " ".join(args))
    elif word == "view" and 1 <= len(args) <= 2:
        client.send("VIEW " + " ".join(args))
    elif word == "focus":
        client.send("FOCUS " + " ".join(args))
    elif word == "key" and args and args[0] in SPEED_KEYS:
        count = int(args[1]) if len(args) > 1 else 1
        delay = float(args[2]) if len(args) > 2 else 3.0
        press_speed_key(args[0], count, delay, client)
    elif word == "key" and args and view_chord(args[0]):
        count = int(args[1]) if len(args) > 1 else 1
        delay = float(args[2]) if len(args) > 2 else 3.0
        press_view_key(args[0], count, delay, client)
    elif word == "kfocus" and args and parse_unit_id(args[0]) is not None:
        chord = args[1] if len(args) > 1 else "f2"
        if not view_chord(chord):
            print(f"  unknown key {chord}")
        else:
            max_steps = int(args[2]) if len(args) > 2 else 40
            key_focus(parse_unit_id(args[0]), chord, max_steps, 3.0, client)
    elif word == "raw" and args:
        client.send(" ".join(args))
    else:
        print("  ? (type help)")
    return True


def main() -> int:
    log = SessionLog(Path("spike_session.log"))
    try:
        client = Client(log)
    except OSError as exc:
        print(f"cannot bind {HOST}:{STATE_PORT}: {exc}")
        return 1
    threading.Thread(target=client.receive_loop, daemon=True).start()
    print(f"listening on {HOST}:{STATE_PORT}, sending to {HOST}:{CMD_PORT}; logging to spike_session.log")
    print("type help for commands")
    client.send("PING")
    try:
        while True:
            try:
                text = input("> ")
            except EOFError:
                break
            log.write(f"## {text}")
            try:
                if not handle(client, text.strip()):
                    break
            except Exception as exc:  # keep the session alive on a bad command
                print(f"  error: {exc}")
    except KeyboardInterrupt:
        pass
    finally:
        client.running = False
        log.write("--- session end ---")
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
