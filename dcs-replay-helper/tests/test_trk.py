from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from replay_helper.dcs.trk import TrackError, read_track

DATA = Path(__file__).parent / "data"


def test_sample_track() -> None:
    t = read_track(DATA / "sample_caucasus.trk")
    assert t.start_tod == 59400 and t.end_tod == pytest.approx(59517.1)
    assert t.duration == pytest.approx(117.1)
    assert (t.date, t.theatre, t.dcs_version) == ("2018-02-01", "Caucasus", "2.9.30.28536")


def test_falls_back_to_mission_start_time(tmp_path: Path) -> None:
    p = tmp_path / "t.trk"
    mission = ('mission = \n{\n\t["date"] = \n\t{\n\t\t["Day"] = 9,\n\t\t["Year"] = 2011,\n\t\t["Month"] = 6,\n'
               '\t}, -- end of ["date"]\n\t["groups"] = { [1] = { ["start_time"] = 0 } },\n'
               '\t["theatre"] = "Syria",\n\t["start_time"] = 28800,\n}\n')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mission", mission)
    t = read_track(p)
    assert (t.start_tod, t.end_tod, t.duration) == (28800, None, None)  # not the nested start_time = 0
    assert (t.date, t.theatre, t.dcs_version) == ("2011-06-09", "Syria", None)


def test_rejects_non_tracks(tmp_path: Path) -> None:
    junk = tmp_path / "junk.trk"
    junk.write_text("hello")
    with pytest.raises(TrackError, match="not a DCS track"):
        read_track(junk)
    empty = tmp_path / "empty.trk"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("other", "x")
    with pytest.raises(TrackError, match="no mission"):
        read_track(empty)
