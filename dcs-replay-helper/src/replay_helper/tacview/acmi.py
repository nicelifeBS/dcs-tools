"""Streaming reader for Tacview ACMI 2.x flight recordings.

Format reference:
https://raia-software-inc.gitbook.io/tacview/technical-documentation/acmi-telemetry-file-format

Only what the Replay Helper needs is kept: global properties, every object's identity (names,
type tags, coalition, parent, first and last appearance) and the events. Positions (T=) --
nearly all of a recording -- are parsed only for aircraft, and only to answer one question:
which aircraft was nearest when a missile, rocket, bomb or ejection seat appeared. That is the
shooter, or the aircraft ejected from; DCS recordings name neither.

Details the spec leaves out, found in real files (see tests/data):
  * Tacview stores bookmarks you add in its UI as ``Event=Bookmark|<ids>|<text>`` lines, with
    its camera state appended to the text after a U+FFFF separator. The text before it is the
    bookmark's name.
  * DCS2ACMI writes FileVersion=2.1 and no Parent for weapons.
"""

from __future__ import annotations

import io
import math
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HEADER = "FileType=text/acmi/tacview"
SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
BOOKMARK_SUFFIX = "￿"
PROGRESS_EVERY_BYTES = 1 << 20
LAUNCH_NEAR_M = 2000.0  # a weapon first seen further than this from any aircraft was not fired by one
EJECT_NEAR_M = 2000.0
EJECT_AFTER_S = 15.0  # an ejection seat may appear after its aircraft is gone (2 s seen in DCS)
WEAPON_KINDS = ("Missile", "Rocket", "Bomb", "Torpedo")
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON = 111_320.0


class AcmiError(ValueError):
    """The file is not a readable ACMI recording."""


@dataclass
class AcmiObject:
    id: int
    first_t: float
    name: str | None = None  # type name, e.g. A-10C_2, AGR_20A
    pilot: str | None = None
    callsign: str | None = None
    group: str | None = None
    tags: frozenset[str] = frozenset()
    coalition: str | None = None
    color: str | None = None
    parent: int | None = None
    removed_t: float | None = None
    near_aircraft: int | None = None  # weapons and ejection seats: nearest aircraft when first seen

    @property
    def label(self) -> str:
        """Who this is, for people: call sign or pilot, with the type name when it differs."""
        who = self.callsign or self.pilot
        if who and self.name and self.name != who:
            return f"{who} ({self.name})"
        return who or self.name or f"#{self.id:x}"

    def has(self, *tags: str) -> bool:
        return all(t in self.tags for t in tags)

    def has_any(self, *tags: str) -> bool:
        return any(t in self.tags for t in tags)

    @property
    def is_aircraft(self) -> bool:
        """An aeroplane or helicopter; not a weapon, debris or a pilot under a parachute."""
        return (self.has_any("FixedWing", "Rotorcraft")
                and not self.has_any("Weapon", "Misc", "Human", "Parachutist"))

    @property
    def is_weapon(self) -> bool:
        return self.has("Weapon") and self.has_any(*WEAPON_KINDS)

    @property
    def is_ejection(self) -> bool:
        """An ejection seat or ejected pilot: PILOT_* in most DCS modules, *_SEAT_* in some (F-4E)."""
        name = (self.name or "").upper()
        return name.startswith("PILOT_") or "_SEAT" in name or self.has("Parachutist")


@dataclass
class AcmiEvent:
    """An Event= line from the file."""

    t: float
    type: str  # Bookmark, Message, Destroyed, TakenOff, Landed, LeftArea, Timeout, ...
    object_ids: tuple[int, ...]
    text: str
    params: dict[str, str] = field(default_factory=dict)  # Timeout's Key:Value tokens


@dataclass
class AcmiFile:
    path: Path
    file_version: str | None = None
    reference_time: datetime | None = None  # UTC; frame times are seconds after it
    recording_time: datetime | None = None
    title: str | None = None
    data_source: str | None = None
    data_recorder: str | None = None
    first_t: float | None = None
    last_t: float | None = None
    objects: dict[int, AcmiObject] = field(default_factory=dict)
    events: list[AcmiEvent] = field(default_factory=list)

    @property
    def reference_tod(self) -> float | None:
        """ReferenceTime as UTC seconds of day."""
        r = self.reference_time
        if r is None:
            return None
        return r.hour * 3600 + r.minute * 60 + r.second + r.microsecond / 1e6


# --------------------------------------------------------------------------------------
# low level: lines and fields
# --------------------------------------------------------------------------------------
def _open_text(path: Path) -> tuple[io.BufferedIOBase, int, Callable[[], None]]:
    """(binary stream of the ACMI text, its uncompressed size, closer)."""
    with path.open("rb") as probe:
        magic = probe.read(6)
    if magic == SEVEN_ZIP_MAGIC:
        raise AcmiError("7-Zip compressed ACMI files are not supported; "
                        "re-save the recording from Tacview as .zip.acmi or .txt.acmi")
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        members = [i for i in zf.infolist() if not i.is_dir()]
        if not members:
            zf.close()
            raise AcmiError("the zip archive is empty")
        member = next((i for i in members if i.filename.lower().endswith(".acmi")), members[0])
        stream = zf.open(member)

        def close() -> None:
            stream.close()
            zf.close()

        return stream, member.file_size, close
    stream = path.open("rb")
    return stream, path.stat().st_size, stream.close


def _trailing_backslashes(s: str) -> int:
    n = 0
    for ch in reversed(s):
        if ch != "\\":
            break
        n += 1
    return n


def _logical_lines(text: io.TextIOBase) -> Iterator[str]:
    """Physical lines joined where a line ends in an (unescaped) backslash: a multi-line value."""
    pending: list[str] = []
    for raw in text:
        line = raw.rstrip("\r\n")
        if _trailing_backslashes(line) % 2 == 1:
            pending.append(line[:-1])
            continue
        if pending:
            pending.append(line)
            yield "\n".join(pending)
            pending = []
        else:
            yield line
    if pending:
        yield "\n".join(pending)


def split_fields(line: str) -> list[str]:
    """Split on commas, honouring the \\, escape."""
    if "\\" not in line:
        return line.split(",")
    out, cur, i, n = [], [], 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            nxt = line[i + 1]
            cur.append(nxt if nxt in ",\\" else ch + nxt)
            i += 2
            continue
        if ch == ",":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _parse_time(value: str) -> datetime | None:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hex_id(token: str) -> int | None:
    token = token.strip()
    if not token or len(token) > 16:
        return None
    try:
        return int(token, 16)
    except ValueError:
        return None


# --------------------------------------------------------------------------------------
# reader
# --------------------------------------------------------------------------------------
_GLOBALS = {
    "ReferenceTime": "reference_time",
    "RecordingTime": "recording_time",
    "Title": "title",
    "DataSource": "data_source",
    "DataRecorder": "data_recorder",
}

_OBJECT_TEXT = {"Name": "name", "Pilot": "pilot", "CallSign": "callsign", "Group": "group",
                "Coalition": "coalition", "Color": "color"}


def _parse_t(value: str, prev: list[float] | None) -> list[float] | None:
    """lon|lat|alt (offsets from the reference point) from a T= value; blanks keep prev."""
    parts = value.split("|", 3)
    out = list(prev) if prev else [math.nan, math.nan, math.nan]
    for i in range(min(3, len(parts))):
        if parts[i]:
            try:
                out[i] = float(parts[i])
            except ValueError:
                pass
    return out


class _Reader:
    def __init__(self, path: Path) -> None:
        self.f = AcmiFile(path=path)
        self.t = 0.0
        self.saw_frame = False
        self.ref_lat = 0.0
        self.pos: dict[int, list[float]] = {}  # aircraft: last lon|lat|alt (kept after removal)

    def frame(self, t: float) -> None:
        self.t = t
        f = self.f
        if not self.saw_frame:
            self.saw_frame = True
            f.first_t = f.last_t = t
        else:
            f.first_t = min(f.first_t, t)
            f.last_t = max(f.last_t, t)

    def global_props(self, fields: list[str]) -> None:
        f = self.f
        for prop in fields:
            key, sep, value = prop.partition("=")
            if not sep:
                continue
            if key == "Event":
                self.event(value)
            elif key in ("ReferenceTime", "RecordingTime"):
                setattr(f, _GLOBALS[key], _parse_time(value))
            elif key == "ReferenceLatitude":
                try:
                    self.ref_lat = float(value)
                except ValueError:
                    pass
            elif key in _GLOBALS:
                setattr(f, _GLOBALS[key], value)

    def event(self, value: str) -> None:
        parts = value.split("|")
        etype, rest = parts[0].strip(), parts[1:]
        if etype == "Timeout":
            params = {}
            for tok in rest:
                k, sep, v = tok.partition(":")
                if sep:
                    params[k.strip()] = v.strip()
            ids = tuple(i for key in ("SourceId", "TargetId")
                        if (i := _hex_id(params.get(key, ""))) is not None)
            self.f.events.append(AcmiEvent(self.t, etype, ids, "", params))
            return
        ids: list[int] = []
        # Object ids come first; the text is whatever is left. Only tokens naming a known
        # object count as ids, so a bookmark called "CAFE" stays text.
        while len(rest) > 1:
            oid = _hex_id(rest[0])
            if oid is None or oid not in self.f.objects:
                break
            ids.append(oid)
            rest = rest[1:]
        text = "|".join(rest)
        text = text.split(BOOKMARK_SUFFIX, 1)[0].strip()
        self.f.events.append(AcmiEvent(self.t, etype, tuple(ids), text))

    def object_props(self, oid: int, fields: list[str]) -> None:
        obj = self.f.objects.get(oid)
        new = obj is None
        if new:
            obj = self.f.objects[oid] = AcmiObject(id=oid, first_t=self.t)
        t_value = None
        for prop in fields:
            if prop.startswith("T="):
                t_value = prop[2:]
                continue
            key, sep, value = prop.partition("=")
            if not sep:
                continue
            if key in _OBJECT_TEXT:
                setattr(obj, _OBJECT_TEXT[key], value)
            elif key == "Type":
                obj.tags = frozenset(t.strip() for t in value.split("+") if t.strip())
            elif key == "Parent":
                obj.parent = _hex_id(value)
        if t_value is None:
            return
        if obj.is_aircraft:
            self.pos[oid] = _parse_t(t_value, self.pos.get(oid))
        elif new and (obj.is_weapon or obj.is_ejection):
            obj.near_aircraft = self.nearest_aircraft(obj, _parse_t(t_value, None))

    def distance(self, a: list[float], b: list[float]) -> float:
        lat = math.radians(self.ref_lat + (a[1] + b[1]) / 2)
        dx = (a[0] - b[0]) * M_PER_DEG_LON * math.cos(lat)
        dy = (a[1] - b[1]) * M_PER_DEG_LAT
        dz = (a[2] - b[2]) if not (math.isnan(a[2]) or math.isnan(b[2])) else 0.0
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def nearest_aircraft(self, obj: AcmiObject, at: list[float]) -> int | None:
        """The aircraft nearest a newly seen weapon or ejection seat, on the same side.

        Weapons: aircraft still there. Ejection seats: also aircraft gone in the last
        EJECT_AFTER_S, as DCS can remove the aircraft before the seat appears.
        """
        if math.isnan(at[0]) or math.isnan(at[1]):
            return None
        ejection = obj.is_ejection
        limit = EJECT_NEAR_M if ejection else LAUNCH_NEAR_M
        best, best_d = None, limit
        for aid, apos in self.pos.items():
            a = self.f.objects[aid]
            if a.removed_t is not None and (not ejection or self.t - a.removed_t > EJECT_AFTER_S):
                continue
            if obj.color and a.color and obj.color != a.color:
                continue
            d = self.distance(at, apos)
            if d <= best_d:
                best, best_d = aid, d
        return best

    def remove(self, oid: int) -> None:
        obj = self.f.objects.get(oid)
        if obj is not None and obj.removed_t is None:
            obj.removed_t = self.t

    def line(self, line: str) -> None:
        if not line:
            return
        c = line[0]
        if c == "#":
            try:
                self.frame(float(line[1:]))
            except ValueError:
                pass
            return
        if c == "-":
            oid = _hex_id(line[1:])
            if oid is not None:
                self.remove(oid)
            return
        if line.startswith("//"):
            return
        comma = line.find(",")
        if comma < 0:
            return
        # Fast path: most of a recording is "id,T=..." position updates for known objects; only
        # aircraft positions are kept.
        rest = line[comma + 1:]
        oid = _hex_id(line[:comma])
        if oid is None:
            return
        if rest.startswith("T=") and "," not in rest and oid in self.f.objects:
            if oid in self.pos:
                self.pos[oid] = _parse_t(rest[2:], self.pos[oid])
            return
        fields = split_fields(rest)
        if oid == 0:
            self.global_props(fields)
        else:
            self.object_props(oid, fields)


def read_acmi(path: str | Path, progress: Callable[[float], None] | None = None) -> AcmiFile:
    """Read an ACMI file (.txt.acmi, .zip.acmi or plain). `progress` gets 0..1 now and then."""
    path = Path(path)
    stream, size, close = _open_text(path)
    try:
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="")
        reader = _Reader(path)
        lines = _logical_lines(text)
        header = next(lines, "").strip()
        if header != HEADER:
            raise AcmiError(f"not a Tacview ACMI text file (first line is {header[:40]!r})")
        version_line = next(lines, "")
        key, _, version = version_line.partition("=")
        if key.strip() != "FileVersion" or not version.strip().startswith("2."):
            raise AcmiError(f"unsupported ACMI version line {version_line[:40]!r} (need FileVersion=2.x)")
        reader.f.file_version = version.strip()
        next_report = PROGRESS_EVERY_BYTES
        for i, line in enumerate(lines):
            reader.line(line)
            if progress is not None and i % 4096 == 0:
                try:
                    pos = stream.tell()
                except (OSError, ValueError):
                    pos = 0
                if pos >= next_report and size:
                    next_report = pos + PROGRESS_EVERY_BYTES
                    progress(min(pos / size, 1.0))
        reader.f.events.sort(key=lambda e: e.t)  # the spec allows out-of-order data
        if progress is not None:
            progress(1.0)
        return reader.f
    except UnicodeDecodeError as exc:  # pragma: no cover - errors="replace" should prevent it
        raise AcmiError(f"cannot decode the file: {exc}") from exc
    finally:
        close()
