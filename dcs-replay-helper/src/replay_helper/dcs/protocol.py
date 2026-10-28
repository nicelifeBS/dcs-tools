"""The line protocol spoken with src/replay_helper/hook/ReplayHelper.lua over localhost UDP.

One message per datagram, a keyword followed by space-separated fields. See the header of
src/replay_helper/hook/ReplayHelper.lua for the authoritative list. Parsing is strict about the keyword and
lenient about extra fields, so a newer hook can add fields without breaking an older app.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

HOST = "127.0.0.1"
STATE_PORT = 47810  # hook -> app
CMD_PORT = 47811  # app -> hook
ACTIONS_SINCE = (0, 2, 0)  # hook version that takes SPEED and FOCUS
CAMERA_SINCE = (0, 3, 0)  # hook version that reports the camera and object speeds (TRACK, OBJECTS, WATCH)


def _hook_since(version: str | None, since: tuple[int, ...]) -> bool:
    v = (version or "").removeprefix("fake-")
    parts = []
    for p in v.split("."):
        if not p.isdigit():
            return False
        parts.append(int(p))
    return tuple(parts) >= since


def hook_takes_actions(version: str | None) -> bool:
    """Whether a hook (or tools/fake_dcs.py, "fake-x.y.z") takes SPEED and FOCUS."""
    return _hook_since(version, ACTIONS_SINCE)


def hook_reports_objects(version: str | None) -> bool:
    """Whether a hook (or tools/fake_dcs.py) takes TRACK, OBJECTS and WATCH and reports cam=."""
    return _hook_since(version, CAMERA_SINCE)


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
    cam: float | None = None  # free camera speed along its view axis, m/s of model time, signed
    tgt: int | None = None  # the WATCHed object
    tgt_along: float | None = None  # its speed along the camera's view axis, m/s, signed
    tgt_side: float | None = None  # and across it

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
class Obj:
    """An aircraft, helicopter or weapon, as the hook measured it. Speeds are m/s, None = unknown."""

    id: int
    kind: str  # plane | heli | air | weapon
    type: str | None  # DCS type name: F-16C_50, AIM-120C
    unit: str | None  # unit name (for a player's slot, the name set in the mission)
    group: str | None
    coalition: str | None
    human: bool
    speed: float | None
    along: float | None  # speed along the camera's view axis, signed
    side: float | None
    dist: float | None  # from the camera, m
    ahead: float | None  # offset along the view axis, m
    age: float | None  # model seconds since the speed was measured


@dataclass(frozen=True)
class ObjEnd:
    count: int  # OBJ lines sent
    total: int  # objects tracked (more than count if the hook capped the list)
    t: float


@dataclass(frozen=True)
class Error:
    text: str


Message = State | Hello | Pong | Armed | Arrived | Disarmed | Focused | FocusFailed | Obj | ObjEnd | Error


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


def _enc(value: str | None) -> str | None:
    """A %XX-encoded text field of OBJ."""
    text = _text(value)
    return None if text is None else unquote(text)


def _signed(value: str | None) -> float | None:
    return _num(value, negative_is_none=False)


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
                cam=_signed(f.get("cam")),
                tgt=int(f["tgt"]) if f.get("tgt", "-").isdigit() else None,
                tgt_along=_signed(f.get("tgt_along")),
                tgt_side=_signed(f.get("tgt_side")),
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
        if word == "OBJ":
            f = _fields(rest)
            return Obj(
                id=int(f["id"]), kind=f.get("kind", ""), type=_enc(f.get("type")), unit=_enc(f.get("unit")),
                group=_enc(f.get("group")), coalition=_enc(f.get("coalition")), human=f.get("human") == "true",
                speed=_signed(f.get("speed")), along=_signed(f.get("along")), side=_signed(f.get("side")),
                dist=_signed(f.get("dist")), ahead=_signed(f.get("ahead")), age=_signed(f.get("age")))
        if word == "OBJ-END":
            f = _fields(rest)
            return ObjEnd(count=int(f["count"]), total=int(f.get("total", f["count"])), t=_req(f, "t"))
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


def cmd_track(on: bool) -> str:
    return "TRACK on" if on else "TRACK off"


def cmd_objects(radius: float | None = None) -> str:
    return "OBJECTS" if radius is None else f"OBJECTS {radius:.0f}"


def cmd_watch(dcs_id: int | None = None) -> str:
    """Report this object's speed along the camera's view axis in every STATE; without an id, stop."""
    return "WATCH" if dcs_id is None else f"WATCH {dcs_id}"
