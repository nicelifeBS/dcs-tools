from __future__ import annotations

from pathlib import Path

from replay_helper.tacview.acmi import read_acmi
from replay_helper.tacview.events import Kind, build_events

SAMPLE = Path(__file__).parent / "data" / "sample_caucasus.zip.acmi"
CWG = Path(__file__).parent / "data" / "Tacview-20261004-131442-DCS-CWG.zip.acmi"


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
        (70.76, Kind.LAUNCH, "AGR_20A ×7", f"{player}"),  # the shooter: nearest when they appeared
        (88.01, Kind.BOOKMARK, "idiot", f"{player}, A-10C #001 (A-10C_2)"),
        (91.06, Kind.DESTROYED, f"{player} lost", "Blue"),
        (91.06, Kind.EJECTION, "Ejection", f"{player}"),
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


def test_every_sample_event_names_the_players_aircraft() -> None:
    events = build_events(read_acmi(SAMPLE))
    assert {(e.aircraft, e.aircraft_unit) for e in events} == {(0x5701, "fubar 1-1 | nicelife")}


def test_air_combat_recording() -> None:
    # F-4E (player, blue) against MiG-29s (red) on GermanyCW: shooters, kills and ejections.
    events = build_events(read_acmi(CWG))
    got = [(round(e.t, 2), e.kind, e.units, e.aircraft) for e in events]
    f4 = "fubar 1-1 | nicelife (F-4E-45MC)"
    assert got == [
        (208.94, Kind.LAUNCH, f4, 0x6f01),
        (224.01, Kind.DESTROYED, "Red", 0x3801),
        (247.75, Kind.LAUNCH, f4, 0x6f01),
        (256.15, Kind.DESTROYED, "Red", 0x3601),
        (258.21, Kind.EJECTION, "MiG-29 12000 ft-1-1 (MiG-29A)", 0x3601),  # seat seen 2 s after the MiG went
        (301.68, Kind.LAUNCH, f4, 0x6f01),
        (319.01, Kind.DESTROYED, "Red", 0x3501),
        (344.59, Kind.EJECTION, f4, 0x6f01),  # F-4E_SEAT_WSO / F-4E_SEAT_PILOT, not PILOT_*
        (345.51, Kind.DESTROYED, "Blue", 0x6f01),
    ]
    assert events[1].aircraft_unit == "MiG-29 12000 ft-3-1"  # DCS's unit name


def test_shooter_is_the_nearest_aircraft_on_the_weapons_side(tmp_path: Path) -> None:
    # lon|lat|alt offsets: 0.001 deg is ~111 m north-south. The red jet is nearer the missile
    # but on the other side; the blue one 2.2 km away is beyond reach.
    body = ("0,ReferenceLatitude=0\n#1\n"
            "1,T=0|0|1000,Type=Air+FixedWing,Name=F-16C,Pilot=Viper-1,Color=Blue\n"
            "2,T=0|0.0005|1000,Type=Air+FixedWing,Name=Su-27,Pilot=Flanker-1,Color=Red\n"
            "3,T=0|0.02|1000,Type=Air+FixedWing,Name=F-15C,Pilot=Eagle-1,Color=Blue\n"
            "#2\n1,T=0|0.001|1000\n"
            "4,T=0|0.0011|1000,Type=Weapon+Missile,Name=AIM-120C,Color=Blue\n"
            "#3\n5,T=1|1|1000,Type=Weapon+Missile,Name=AIM-9X,Color=Blue\n")
    events = build_events(read_acmi(write(tmp_path, body)))
    assert [(e.label, e.units, e.aircraft, e.aircraft_unit) for e in events] == [
        ("AIM-120C", "Viper-1 (F-16C)", 1, "Viper-1"),  # from Viper-1's updated position
        ("AIM-9X", "Blue", None, ""),  # nobody near: no shooter
    ]


def test_ejection_seat_after_its_aircraft_is_gone(tmp_path: Path) -> None:
    body = ("#1\n1,T=0|0|3000,Type=Air+FixedWing,Name=MiG-29A,Pilot=Fulcrum-1,Color=Red\n"
            "#5\n-1\n#7\n2,T=0|0.001|2900,Type=Misc+Shrapnel,Name=PILOT_SU27_SEAT,Color=Red\n"
            "#40\n3,T=0|0|100,Type=Ground+Light+Human+Air+Parachutist,Name=F-4E_SEAT_PILOT\n")
    events = build_events(read_acmi(write(tmp_path, body)))
    got = [(e.t, e.kind, e.units, e.aircraft) for e in events]
    assert (7, Kind.EJECTION, "Fulcrum-1 (MiG-29A)", 1) in got
    assert (40, Kind.EJECTION, "", None) in got  # long after the MiG went: nobody to show
    assert not any(k is Kind.DESTROYED and "SEAT" in str(u) for _, k, u, _ in got)


def test_bookmark_aircraft_is_the_first_aircraft_it_names(tmp_path: Path) -> None:
    body = ("#1\n1,Type=Ground+Vehicle,Name=T-72\n2,Type=Air+Rotorcraft,Name=AH-64D,Pilot=Hammer-1\n"
            "#2\n0,Event=Bookmark|1|2|Gun run\n0,Event=Bookmark|1|Tank\n")
    events = build_events(read_acmi(write(tmp_path, body)))
    assert [(e.label, e.aircraft, e.aircraft_unit) for e in events] == [
        ("Gun run", 2, "Hammer-1"), ("Tank", None, "")]
