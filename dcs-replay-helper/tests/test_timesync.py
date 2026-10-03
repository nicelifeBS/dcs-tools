from __future__ import annotations

from datetime import date

import pytest

from replay_helper.settings import Settings
from replay_helper.timesync import SyncSettings, auto_tz_minutes, compute, fine_for_sync, fmt_tz

H = 3600


@pytest.mark.parametrize("ref,start,tz", [
    (12.5 * H, 16.5 * H, 240),          # the sample: Caucasus, UTC+4
    (12 * H, 16.5 * H, 270),            # Afghanistan, UTC+4:30
    (15 * H, 7 * H, -480),              # Nevada in winter, UTC-8
    (23.5 * H, 3.5 * H, 240),           # local time is past midnight
    (15 * H, 12 * H, -180),             # South Atlantic, UTC-3
    (20 * H, 6 * H, 600),               # Marianas, UTC+10, local time the next day
    (12.5 * H + 70, 16.5 * H, 240),     # recording started 70 s after the mission
])
def test_auto_time_zone(ref, start, tz) -> None:
    assert auto_tz_minutes(ref, start) == tz


def test_sample_offset_is_zero() -> None:
    r = compute(SyncSettings(), 45000, 59400, date(2018, 2, 1), date(2018, 2, 1))
    assert (r.offset, r.tz_minutes, r.auto, r.warning) == (0, 240, True, None)


def test_late_recording_offset() -> None:
    # Tacview joined 70 s into the mission: its t=0 is replay t=70.
    assert compute(SyncSettings(), 12.5 * H + 70, 16.5 * H).offset == pytest.approx(70)


def test_manual_time_zone_and_fine() -> None:
    r = compute(SyncSettings(tz_minutes=180, fine_s=1.5), 45000, 59400)
    assert r.offset == pytest.approx(-3600 + 1.5) and not r.auto and r.tz_minutes == 180


def test_midnight_wrap() -> None:
    assert compute(SyncSettings(), 23.5 * H, 3.5 * H).offset == pytest.approx(0)


def test_unknown_times_use_fine_only() -> None:
    assert compute(SyncSettings(fine_s=2.0), None, 59400).offset == 2.0
    assert compute(SyncSettings(fine_s=2.0), 45000, None).offset == 2.0


def test_date_warning() -> None:
    assert compute(SyncSettings(), 45000, 59400, date(2018, 2, 1), date(2018, 2, 2)).warning is None
    assert "2024-06-01" in compute(SyncSettings(), 45000, 59400, date(2018, 2, 1), date(2024, 6, 1)).warning


def test_fine_for_sync() -> None:
    # Running in is at Tacview 67.95; the replay is paused on that moment at 70.00.
    fine = fine_for_sync(SyncSettings(fine_s=5.0), 45000, 59400, 67.95, 70.0)
    assert fine == pytest.approx(2.05)  # replaces the old fine adjustment
    assert compute(SyncSettings(fine_s=fine), 45000, 59400).offset + 67.95 == pytest.approx(70.0)


def test_fmt_tz() -> None:
    assert [fmt_tz(m) for m in (240, 270, -480, 0, None)] == ["UTC+4:00", "UTC+4:30", "UTC-8:00", "UTC+0:00", "?"]


def test_settings_roundtrip(tmp_path) -> None:
    s = Settings(tmp_path / "s.json")
    assert s.sync_for("x.acmi") == SyncSettings()
    s.set_sync("x.acmi", SyncSettings(180, 2.5))
    assert Settings(tmp_path / "s.json").sync_for("x.acmi") == SyncSettings(180, 2.5)
    s.set_sync("x.acmi", SyncSettings())  # defaults are not stored
    assert Settings(tmp_path / "s.json").data["sync"] == {}


def test_settings_survive_a_corrupt_file(tmp_path) -> None:
    p = tmp_path / "s.json"
    p.write_text("{not json")
    s = Settings(p)
    assert s.sync_for("x.acmi") == SyncSettings()
    s.set("limit", 4)
    assert Settings(p).get("limit") == 4
