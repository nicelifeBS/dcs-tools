"""Lining Tacview time up with DCS replay time.

Tacview frame times count from ReferenceTime, which the spec defines as UTC. DCS model time
counts from mission start, and the mission's start time is local time on the map. So

    replay t = acmi t + offset,   offset = (ReferenceTime of day + time zone) - mission start + fine

The time zone is normally worked out by rounding (mission start - ReferenceTime of day) to
15 minutes -- for the sample Caucasus recording that is +4:00 (UTC+4) and the offset comes
out 0. When the Tacview recording did not start with the mission (joining a server late,
starting the recorder by hand) the remainder becomes the offset; the fine adjustment, or
"sync to this event", corrects whatever is left.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DAY = 86400.0
TZ_STEP_MIN = 15
TZ_MIN_H, TZ_MAX_H = -12, 14


@dataclass(frozen=True)
class SyncSettings:
    tz_minutes: int | None = None  # None: work it out
    fine_s: float = 0.0


@dataclass(frozen=True)
class SyncResult:
    offset: float  # replay t = acmi t + offset
    tz_minutes: int | None  # in effect (auto or manual); None when it cannot be known
    auto: bool
    warning: str | None = None


def _wrap(seconds: float, low: float, high: float) -> float:
    while seconds >= high:
        seconds -= DAY
    while seconds < low:
        seconds += DAY
    return seconds


def auto_tz_minutes(reference_tod: float, start_tod: float) -> int:
    """Mission start minus ReferenceTime of day, rounded to 15 minutes, within UTC-12..UTC+14."""
    diff = _wrap(start_tod - reference_tod, TZ_MIN_H * 3600 - 450, TZ_MAX_H * 3600 + 450)
    return int(round(diff / 60 / TZ_STEP_MIN)) * TZ_STEP_MIN


def compute(settings: SyncSettings, reference_tod: float | None, start_tod: float | None,
            acmi_date: date | None = None, mission_date: date | None = None) -> SyncResult:
    """The offset for these settings. Without both times only the fine adjustment applies."""
    if reference_tod is None or start_tod is None:
        return SyncResult(offset=settings.fine_s, tz_minutes=settings.tz_minutes,
                          auto=settings.tz_minutes is None)
    auto = settings.tz_minutes is None
    tz = auto_tz_minutes(reference_tod, start_tod) if auto else settings.tz_minutes
    base = _wrap(reference_tod + tz * 60 - start_tod, -DAY / 2, DAY / 2)
    warning = None
    if acmi_date is not None and mission_date is not None and abs((acmi_date - mission_date).days) > 1:
        warning = (f"The Tacview recording is dated {acmi_date.isoformat()} but the mission "
                   f"{mission_date.isoformat()}: is it the recording of this track?")
    return SyncResult(offset=base + settings.fine_s, tz_minutes=tz, auto=auto, warning=warning)


def fine_for_sync(settings: SyncSettings, reference_tod: float | None, start_tod: float | None,
                  event_acmi_t: float, replay_now: float) -> float:
    """The fine adjustment that puts an event at `replay_now` (the replay is paused on it)."""
    base = compute(SyncSettings(settings.tz_minutes, 0.0), reference_tod, start_tod).offset
    return replay_now - event_acmi_t - base


def fmt_tz(minutes: int | None) -> str:
    if minutes is None:
        return "?"
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}:{m:02d}"
