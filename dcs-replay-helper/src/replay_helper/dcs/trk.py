"""Reading a DCS track (.trk) for its mission clock, without DCS running.

A .trk is a zip. The parts used here:
  track_data/times   absoluteTime0 / absoluteTime1: mission time of day at the start and end
  mission            the mission's Lua table: start_time, date, theatre
  track_data/version DCS build

Always open the track you are going to replay. While a track plays, DCS records a new
LastMissionTrack.trk, so "the newest file in Tracks" is the wrong one.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


class TrackError(ValueError):
    """Not a readable DCS track."""


@dataclass(frozen=True)
class TrackInfo:
    path: Path
    start_tod: float | None  # mission time of day at model time 0, seconds
    end_tod: float | None  # at the end of the recording
    date: str | None  # YYYY-MM-DD
    theatre: str | None
    dcs_version: str | None

    @property
    def duration(self) -> float | None:
        if self.start_tod is None or self.end_tod is None:
            return None
        return self.end_tod - self.start_tod


# Top-level keys of the mission table are indented by exactly one tab.
_START = re.compile(r'^\t\["start_time"\]\s*=\s*([\d.]+)', re.M)
_THEATRE = re.compile(r'^\t\["theatre"\]\s*=\s*"([^"]*)"', re.M)
_DATE = re.compile(r'^\t\["date"\]\s*=\s*\{(.*?)\}', re.M | re.S)
_DATE_PART = re.compile(r'\["(Year|Month|Day)"\]\s*=\s*(\d+)')
_TIMES = re.compile(r"(absoluteTime[01])\s*=\s*([\d.]+)")


def read_track(path: str | Path) -> TrackInfo:
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise TrackError(f"not a DCS track: {exc}") from exc
    with zf:
        names = set(zf.namelist())
        if "mission" not in names:
            raise TrackError("not a DCS track (no mission inside)")

        def text(name: str) -> str | None:
            if name not in names:
                return None
            return zf.read(name).decode("utf-8", errors="replace")

        times = dict((k, float(v)) for k, v in _TIMES.findall(text("track_data/times") or ""))
        mission = text("mission") or ""
        version_lines = (text("track_data/version") or "").splitlines()

    start = _START.search(mission)
    start_tod = times.get("absoluteTime0", float(start.group(1)) if start else None)
    theatre = _THEATRE.search(mission)
    date = None
    if (block := _DATE.search(mission)) is not None:
        parts = {k: int(v) for k, v in _DATE_PART.findall(block.group(1))}
        if {"Year", "Month", "Day"} <= parts.keys():
            date = f"{parts['Year']:04d}-{parts['Month']:02d}-{parts['Day']:02d}"
    version = next((line.split(" ", 1)[0][4:] for line in version_lines if line.startswith("DCS/")), None)
    return TrackInfo(path=path, start_tod=start_tod, end_tod=times.get("absoluteTime1"), date=date,
                     theatre=theatre.group(1) if theatre else None, dcs_version=version)
