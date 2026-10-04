"""The line protocol spoken with src/replay_helper/hook/ReplayHelper.lua over localhost UDP.

One message per datagram, a keyword followed by space-separated fields. See the header of
src/replay_helper/hook/ReplayHelper.lua for the authoritative list. Parsing is strict about the keyword and
lenient about extra fields, so a newer hook can add fields without breaking an older app.
"""

from __future__ import annotations

from dataclasses import dataclass

HOST = "127.0.0.1"
STATE_PORT = 47810  # hook -> app
CMD_PORT = 47811  # app -> hook
ACTIONS_SINCE = (0, 2, 0)  # hook version that takes SPEED and FOCUS


def hook_takes_actions(version: str | None) -> bool:
    """Whether a hook (or tools/fake_dcs.py, "fake-x.y.z") takes SPEED and FOCUS."""
    v = (version or "").removeprefix("fake-")
    parts = []
    for p in v.split("."):
        if not p.isdigit():
            return False
        parts.append(int(p))
    return tuple(parts) >= ACTIONS_SINCE


@dataclass(frozen=True)
class State:
    t: float  # model time, seconds since mission start
    rt: float  # DCS real time
    speed: float | None  # measured model/real ratio; None until two samples agree
    accel: float | None  # time acceleration DCS is commanding; None if unavailable
    paused: bool
    track: bool  # a .trk replay is playing
    stop: float | None  # armed stop target
    start_tod: float | None  # mission start, seconds of day (local map time)
    date: str | None  # YYYY-MM-DD
    theatre: str | None

    @property
    def mission_tod(self) -> float | None:
        """Mission time of day for this model time, seconds (may exceed 86400)."""
        return None if self.start_tod is None else self.start_tod + self.t


@dataclass(frozen=True)
class Hello:
    version: str


@dataclass(frozen=True)
class Pong:
    version: str


@dataclass(frozen=True)
class Armed:
    target: float
    now: float


@dataclass(frozen=True)
class Arrived:
    t: float
    target: float
    over: float


@dataclass(frozen=True)
class Disarmed:
    reason: str  # request | restart | mission_end


@dataclass(frozen=True)
class Focused:
    id: int  # DCS unit id now in F2 view
    steps: int  # F2 steps it took


@dataclass(frozen=True)
class FocusFailed:
    id: int | None
    reason: str  # not_found | unavailable | no_camera | cycled | max_steps | cancelled | restart | mission_end


@dataclass(frozen=True)
class Error:
    text: str


Message = State | Hello | Pong | Armed | Arrived | Disarmed | Focused | FocusFailed | Error


def _fields(parts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep:
            out[key] = value
    return out


def _num(value: str | None, *, negative_is_none: bool = True) -> float | None:
    """Parse a number; the hook writes -1 for 'unknown' in fields that are never negative."""
    if value is None:
        return None
    try:
        n = float(value)
    except ValueError:
        return None
    if negative_is_none and n < 0:
        return None
    return n


def _req(f: dict[str, str], key: str) -> float:
    return float(f[key])


def _text(value: str | None) -> str | None:
    return None if value in (None, "", "-") else value


def parse(line: str) -> Message | None:
    """Parse one datagram from the hook. Returns None for anything unrecognised or malformed."""
    parts = line.strip().split()
    if not parts:
        return None
    word, rest = parts[0], parts[1:]
    try:
        if word == "STATE":
            f = _fields(rest)
            return State(
                t=_req(f, "t"),
                rt=_req(f, "rt"),
                speed=_num(f.get("speed")),
                accel=_num(f.get("accel")),
                paused=f.get("paused") == "true",
                track=f.get("track") == "true",
                stop=_num(f.get("stop")),
                start_tod=_num(f.get("start_tod")),
                date=_text(f.get("date")),
                theatre=_text(f.get("theatre")),
            )
        if word == "HELLO":
            return Hello(version=rest[0] if rest else "")
        if word == "PONG":
            return Pong(version=rest[0] if rest else "")
        if word == "ARMED":
            f = _fields(rest)
            return Armed(target=_req(f, "target"), now=_req(f, "now"))
        if word == "ARRIVED":
            f = _fields(rest)
            return Arrived(t=_req(f, "t"), target=_req(f, "target"), over=_req(f, "over"))
        if word == "DISARMED":
            return Disarmed(reason=_fields(rest).get("reason", ""))
        if word == "FOCUSED":
            f = _fields(rest)
            return Focused(id=int(f["id"]), steps=int(f.get("steps", "0")))
        if word == "FOCUS-FAILED":
            f = _fields(rest)
            return FocusFailed(id=int(f["id"]) if f.get("id", "-").isdigit() else None,
                               reason=f.get("reason", ""))
        if word == "ERR":
            return Error(text=" ".join(rest))
    except (KeyError, ValueError):
        return None
    return None


# --- commands (app -> hook) -----------------------------------------------------------

def cmd_ping() -> str:
    return "PING"


def cmd_pause() -> str:
    return "PAUSE"


def cmd_resume() -> str:
    return "RESUME"


def cmd_armstop(t: float) -> str:
    return f"ARMSTOP {t:.3f}"


def cmd_disarm() -> str:
    return "DISARM"


def cmd_speed(step: str) -> str:
    """step: UP, DOWN or NORMAL."""
    return f"SPEED {step}"


def cmd_focus(dcs_id: int | None = None, unit_name: str | None = None) -> str:
    """F2 on a unit; without an id, cancel. The unit name is the fallback if the id is unknown."""
    if dcs_id is None:
        return "FOCUS"
    name = " ".join((unit_name or "").split())  # one line, single spaces
    return f"FOCUS {dcs_id} {name}".rstrip()
