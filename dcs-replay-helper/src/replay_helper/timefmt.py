"""Formatting times for display."""

from __future__ import annotations

import math


def fmt_model(t: float | None) -> str:
    """Model time (seconds since mission start) as M:SS.s, or H:MM:SS.s from an hour on."""
    if t is None or math.isnan(t):
        return "--:--.-"
    sign = "-" if t < 0 else ""
    tenths = int(round(abs(t) * 10))
    h, rem = divmod(tenths, 36000)
    m, rem = divmod(rem, 600)
    s, d = divmod(rem, 10)
    if h:
        return f"{sign}{h}:{m:02d}:{s:02d}.{d}"
    return f"{sign}{m}:{s:02d}.{d}"


def fmt_tod(seconds: float | None) -> str:
    """Seconds of day as HH:MM:SS (wraps past midnight)."""
    if seconds is None or math.isnan(seconds):
        return "--:--:--"
    total = int(math.floor(seconds)) % 86400
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_speed(x: float | None) -> str:
    if x is None:
        return "?"
    if x >= 1 and abs(x - round(x)) < 0.05:
        return f"{round(x)}x"
    return f"{round(x, 2):g}x"
