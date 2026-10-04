from __future__ import annotations

from pathlib import Path

from replay_helper.tacview.acmi import read_acmi
from replay_helper.tacview.events import Kind, build_events

SAMPLE = Path(__file__).parent / "data" / "sample_caucasus.zip.acmi"


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "t.txt.acmi"
    p.write_text("FileType=text/acmi/tacview\nFileVersion=2.2\n" + body, encoding="utf-8")
    return p


def test_sample_events() -> None:
    events = build_events(read_acmi(SAMPLE))
    got = [(e.t, e.kind, e.label, e.units) for e in events]
    player = "fubar 1-1 | nicelife (A-10C_2)"
    assert got == [
        (67.95, Kind.BOOKMARK, "Running in", f"{player}, A-10C #001 (A-10C_2)"),
        (70.76, Kind.LAUNCH, "AGR_20A ×7", "Blue"),
        (88.01, Kind.BOOKMARK, "idiot", f"{player}, A-10C #001 (A-10C_2)"),
        (91.06, Kind.DESTROYED, f"{player} lost", "Blue"),
        (91.06, Kind.EJECTION, "Ejection", "Blue"),
    ]
    assert len(events[1].object_ids) == 7
    assert {e.side for e in events} == {"Blue"}  # bookmarks take the side of their first object


def test_salvos_split_by_gap_and_side(tmp_path: Path) -> None:
    body = "".join(
        f"#{t}\n{oid},Type=Weapon+Missile,Name=AIM-120C,Color={color}\n"
        for t, oid, color in [(1, "a1", "Blue"), (2.5, "a2", "Blue"), (5, "a3", "Blue"), (5.1, "b1", "Red")])
    events = build_events(read_acmi(write(tmp_path, body)))
    assert [(e.t, e.label, e.units) for e in events] == [
        (1, "AIM-120C ×2", "Blue"), (5, "AIM-120C", "Blue"), (5.1, "AIM-120C", "Red")]
    assert [e.side for e in events] == ["Blue", "Blue", "Red"]


def test_launch_names_the_shooter_when_parent_is_known(tmp_path: Path) -> None:
    body = ("#1\n10,Type=Air+FixedWing,Name=F-16C,CallSign=Viper11\n"
            "#2\n20,Type=Weapon+Missile,Name=AIM-9X,Parent=10\n")
    e = build_events(read_acmi(write(tmp_path, body)))[0]
    assert (e.kind, e.label, e.units) == (Kind.LAUNCH, "AIM-9X", "Viper11 (F-16C)")


def test_only_units_without_left_area_or_destroyed_count_as_lost(tmp_path: Path) -> None:
    body = ("#1\n1,Type=Air+FixedWing,Name=Su-27,Color=Red\n2,Type=Air+FixedWing,Name=Su-33,Color=Red\n"
            "3,Type=Ground+Vehicle,Name=T-72,Color=Red\n4,Type=Projectile+Shell,Name=Shell\n"
            "5,Type=Misc+Decoy+Flare\n6,Type=Weapon+Bomb,Name=Mk-82\n"
            "#9\n0,Event=LeftArea|2|\n0,Event=Destroyed|3|\n-1\n-2\n-3\n-4\n-5\n-6\n")
    got = [(e.kind, e.label) for e in build_events(read_acmi(write(tmp_path, body)))]
    assert (Kind.DESTROYED, "Su-27 lost") in got
    assert (Kind.DESTROYED, "T-72 destroyed") in got  # explicit event, not a second "lost"
    assert (Kind.OTHER, "Su-33 left the area") in got
    assert not any(k is Kind.DESTROYED and "Su-33" in label for k, label in got)
    assert sum(k is Kind.DESTROYED for k, _ in got) == 2


def test_explicit_event_kinds_and_debug_ignored(tmp_path: Path) -> None:
    body = ("#1\n1,Name=C172,Pilot=Iceman\n#2\n0,Event=TakenOff|1|Iceman has taken off\n"
            "0,Event=Debug|noise\n0,Event=Landed|1|\n0,Event=Message|1|Hello\n0,Event=LeftArea|1|\n")
    got = [(e.kind, e.label) for e in build_events(read_acmi(write(tmp_path, body)))]
    assert got == [(Kind.TAKEOFF, "Iceman has taken off"), (Kind.LANDING, "Iceman (C172) landed"),
                   (Kind.MESSAGE, "Hello"), (Kind.OTHER, "Iceman (C172) left the area")]
