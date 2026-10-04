"""The events a user can seek to, built from an ACMI recording.

Explicit events come from the file's Event= lines. Three kinds are derived, because DCS
recordings rarely carry them:

  * Launch    -- a missile, rocket, bomb or torpedo object appears. Launches of the same weapon
                 by the same coalition less than SALVO_GAP_S apart are one salvo ("AGR_20A x7").
                 DCS2ACMI writes no Parent, so the shooter is usually unknown.
  * Removed   -- an aircraft, ground unit or ship disappears without a LeftArea event (and
                 without an explicit Destroyed): almost always destroyed. Tacview infers its
                 own Destroyed events the same way.
  * Ejection  -- an ejection seat or pilot object (DCS names them PILOT_*) appears.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .acmi import AcmiFile, AcmiObject

SALVO_GAP_S = 2.0
EJECTION_GAP_S = 5.0
WEAPON_KINDS = ("Missile", "Rocket", "Bomb", "Torpedo")
UNIT_CLASSES = ("Air", "Ground", "Sea")


class Kind(Enum):
    BOOKMARK = "Bookmark"
    LAUNCH = "Launch"
    DESTROYED = "Destroyed"  # explicit Destroyed events and derived removals
    EJECTION = "Ejection"
    TAKEOFF = "Take-off"
    LANDING = "Landing"
    MESSAGE = "Message"
    OTHER = "Other"  # LeftArea, Timeout, unknown types


_EXPLICIT = {
    "Bookmark": Kind.BOOKMARK,
    "Destroyed": Kind.DESTROYED,
    "TakenOff": Kind.TAKEOFF,
    "Landed": Kind.LANDING,
    "Message": Kind.MESSAGE,
}


@dataclass(frozen=True)
class Event:
    t: float  # ACMI time (seconds after ReferenceTime)
    kind: Kind
    label: str
    units: str  # who is involved, for display
    object_ids: tuple[int, ...] = ()
    side: str = ""  # Tacview color of the side involved ("Blue", "Red", ...), "" if unknown


def _units(f: AcmiFile, ids) -> str:
    labels = []
    for oid in ids:
        obj = f.objects.get(oid)
        label = obj.label if obj else f"#{oid:x}"
        if label not in labels:
            labels.append(label)
    return ", ".join(labels)


def _side(o: AcmiObject) -> str:
    # Color is the side as Tacview shows it; DCS2ACMI's Coalition names ("Enemies") mislead.
    return o.color or o.coalition or ""


def _ids_side(f: AcmiFile, ids) -> str:
    """The side of the first of these objects that has one."""
    for oid in ids:
        obj = f.objects.get(oid)
        if obj is not None and _side(obj):
            return _side(obj)
    return ""


def _is_weapon(o: AcmiObject) -> bool:
    return o.has("Weapon") and o.has_any(*WEAPON_KINDS)


def _is_unit(o: AcmiObject) -> bool:
    return o.has_any(*UNIT_CLASSES) and not o.has_any("Weapon", "Projectile", "Misc", "Navaid")


def _is_ejection(o: AcmiObject) -> bool:
    return (o.name or "").upper().startswith("PILOT_")


def _explicit_events(f: AcmiFile) -> list[Event]:
    out = []
    for e in f.events:
        if e.type == "Debug":
            continue
        kind = _EXPLICIT.get(e.type, Kind.OTHER)
        if e.type == "Timeout":
            p = e.params
            bits = [p.get("AmmoType"), p.get("Outcome")]
            label = "Timeout " + " ".join(b for b in bits if b)
        elif kind is Kind.BOOKMARK:
            label = e.text or "(unnamed bookmark)"
        elif e.text:
            label = e.text
        else:
            label = {"Destroyed": "destroyed", "TakenOff": "took off", "Landed": "landed",
                     "LeftArea": "left the area"}.get(e.type, e.type)
            if e.object_ids:
                label = f"{_units(f, e.object_ids[:1])} {label}"
        out.append(Event(e.t, kind, label, _units(f, e.object_ids), e.object_ids,
                         _ids_side(f, e.object_ids)))
    return out


def _chains(objs: list[AcmiObject], gap: float) -> list[list[AcmiObject]]:
    """Group objects (sorted by first_t) into runs whose consecutive starts are <= gap apart."""
    runs: list[list[AcmiObject]] = []
    for o in objs:
        if runs and o.first_t - runs[-1][-1].first_t <= gap:
            runs[-1].append(o)
        else:
            runs.append([o])
    return runs


def _launches(f: AcmiFile) -> list[Event]:
    by_kind: dict[tuple[str, str], list[AcmiObject]] = {}
    for o in f.objects.values():
        if _is_weapon(o):
            by_kind.setdefault((o.name or "weapon", _side(o)), []).append(o)
    out = []
    for (name, side), objs in by_kind.items():
        objs.sort(key=lambda o: o.first_t)
        for run in _chains(objs, SALVO_GAP_S):
            label = f"{name} ×{len(run)}" if len(run) > 1 else name
            shooters = [o.parent for o in run if o.parent is not None]
            units = _units(f, dict.fromkeys(shooters)) if shooters else side
            out.append(Event(run[0].first_t, Kind.LAUNCH, label, units, tuple(o.id for o in run), side))
    return out


def _removals(f: AcmiFile) -> list[Event]:
    left = {oid for e in f.events if e.type == "LeftArea" for oid in e.object_ids}
    destroyed = {oid for e in f.events if e.type == "Destroyed" for oid in e.object_ids}
    out = []
    for o in f.objects.values():
        if o.removed_t is None or not _is_unit(o) or o.id in left or o.id in destroyed:
            continue
        out.append(Event(o.removed_t, Kind.DESTROYED, f"{o.label} lost", _side(o), (o.id,), _side(o)))
    return out


def _ejections(f: AcmiFile) -> list[Event]:
    objs = sorted((o for o in f.objects.values() if _is_ejection(o)), key=lambda o: o.first_t)
    out = []
    for run in _chains(objs, EJECTION_GAP_S):
        out.append(Event(run[0].first_t, Kind.EJECTION, "Ejection", _side(run[0]),
                         tuple(o.id for o in run), _side(run[0])))
    return out


def build_events(f: AcmiFile) -> list[Event]:
    """Every seekable event in the recording, in time order."""
    events = _explicit_events(f) + _launches(f) + _removals(f) + _ejections(f)
    events.sort(key=lambda e: e.t)  # stable: same-time events keep file order
    return events
