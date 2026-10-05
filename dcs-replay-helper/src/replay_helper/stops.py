"""Stop before bookmarks: while the replay plays on its own, pause it ahead of the next bookmark.

Outside a seek (the seek controller IDLE or READY), the hook's stop is kept armed at the next
bookmark minus the pre-roll, so watching or recording through one moment never runs past the
next one. The hook pauses on that frame, exactly as for a seek, and nothing else changes: the
speed and the camera stay as they are. Press Play to go on to the bookmark and the next stop.

A bookmark is skipped when its pre-roll point is already behind the replay, and so is every
bookmark up to the target of the last seek: having jumped to a bookmark, Play runs through it.

The hook holds one stop. A seek arms its own, which replaces this one; once the seek is over
the next bookmark is armed again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .dcs.protocol import Arrived, Disarmed, Error, Message, State
from .seek import MIN_LEAD_S, Phase

RESTART_JUMP_S = 1.0  # the replay clock going back by more than this: the track restarted


@dataclass(frozen=True)
class Stop:
    t: float  # where the replay pauses: the bookmark's time minus the pre-roll
    bookmark_t: float  # replay time of the bookmark
    label: str


class BookmarkStops(QObject):
    armedChanged = Signal(object)  # Stop | None: the stop now armed for the next bookmark
    reached = Signal(object, float)  # (Stop, t): paused before a bookmark

    def __init__(self, link, seek, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._seek = seek
        self._enabled = True
        self._preroll = 0.0
        self._bookmarks: list[tuple[float, str]] = []  # (replay time, label), sorted
        self._after: float | None = None  # bookmarks up to the last seek's target are skipped
        self._armed: Stop | None = None
        self._now: float | None = None  # the replay clock: the last STATE, or a later ARRIVED

        link.stateChanged.connect(self._on_state)
        link.message.connect(self._on_message)
        link.connectedChanged.connect(lambda _connected: self.update())
        seek.phaseChanged.connect(self._on_seek_phase)

    # --- public -----------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def armed(self) -> Stop | None:
        return self._armed

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.update()

    def set_preroll(self, preroll: float) -> None:
        self._preroll = max(preroll, 0.0)
        self.update()

    def set_bookmarks(self, bookmarks: Sequence[tuple[float, str]]) -> None:
        self._bookmarks = sorted(bookmarks)
        self.update()

    def next_stop(self) -> Stop | None:
        """The stop for the next bookmark the replay can still pause ahead of, if any."""
        if self._now is None:
            return None
        lead = self._now + MIN_LEAD_S
        armed = self._armed
        for bookmark_t, label in self._bookmarks:
            if self._after is not None and bookmark_t <= self._after + 1e-3:
                continue
            t = bookmark_t - self._preroll
            # The lead is for arming: a stop already armed stays until the hook reaches it.
            if t > lead or (armed is not None and abs(t - armed.t) < 1e-3 and t > self._now):
                return Stop(t, bookmark_t, label)
        return None

    def update(self) -> None:
        """Arm, move or drop the stop to match the replay, the bookmarks and the settings."""
        if not self._link.connected or self._link.state is None:
            self._set_armed(None)
            return
        if self._seek.phase not in (Phase.IDLE, Phase.READY):
            self._set_armed(None)  # the seek's own stop replaces ours
            return
        want = self.next_stop() if self._enabled else None
        have = self._armed
        if want is None:
            if have is not None:
                self._link.disarm()
                self._set_armed(None)
        elif have is None or abs(have.t - want.t) > 1e-3:
            self._link.arm_stop(want.t)
            self._set_armed(want)
        elif have != want:
            self._set_armed(want)  # same time, renamed bookmark

    # --- internals --------------------------------------------------------------------
    def _set_armed(self, stop: Stop | None) -> None:
        if stop != self._armed:
            self._armed = stop
            self.armedChanged.emit(stop)

    def _on_seek_phase(self, phase: Phase) -> None:
        if phase is Phase.READY:
            self._after = self._seek.event_t
        self.update()

    def _on_state(self, s: State) -> None:
        if self._now is not None and s.t < self._now - RESTART_JUMP_S:
            self._after = None
        self._now = s.t
        self.update()

    def _on_message(self, msg: Message) -> None:
        if isinstance(msg, Arrived):
            self._now = max(self._now or 0.0, msg.t)  # before the STATE that shows it
        stop = self._armed
        if stop is None:
            return
        if isinstance(msg, Arrived) and abs(msg.target - stop.t) < 1e-3:
            self._set_armed(None)
            self.reached.emit(stop, msg.t)
            self.update()  # arm the next one; the replay stays paused until Play
        elif isinstance(msg, Disarmed) and msg.reason != "request":
            self._set_armed(None)  # the hook dropped it (track restart, mission end)
        elif isinstance(msg, Error) and msg.text.startswith("behind"):
            self._set_armed(None)  # passed while the command was on its way; the next STATE moves on
