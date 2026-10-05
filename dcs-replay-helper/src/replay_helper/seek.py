"""Seek forward to an event with a pre-roll.

A seek, step by step (each waits for DCS to confirm before the next):

    PAUSING   pause the replay
    SPEEDING  set the seek speed while paused, so the replay never runs faster than asked
    ARMING    arm the hook's stop at event - pre-roll (the hook refuses a target behind it)
    RUNNING   resume; the hook pauses on the exact frame the stop is reached
    SLOWING   set the playback speed while still paused
    READY     paused at the pre-roll point

play() from READY resumes and goes back to IDLE.

Replays only run forward, so a target at or behind the playhead is refused up front. Anything
unexpected -- the track restarting, someone pausing mid-seek, the link dropping, DCS not
answering -- ends the seek with `failed` and leaves the replay paused where it is.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from .dcs.protocol import Armed, Arrived, Disarmed, Error, Message, State

CONFIRM_TIMEOUT_S = 3.0  # for DCS to confirm a pause or an armed stop
MIN_LEAD_S = 0.2  # a stop closer than this to the playhead counts as already passed


class Phase(Enum):
    IDLE = "idle"
    PAUSING = "pausing"
    SPEEDING = "speeding"
    ARMING = "arming"
    RUNNING = "running"
    SLOWING = "slowing"
    READY = "ready"


class SeekError(ValueError):
    """The seek cannot start (target behind the playhead, no connection, ...)."""


class SeekController(QObject):
    phaseChanged = Signal(object)  # Phase
    ready = Signal(float, float)  # (event t, stop t): paused at the pre-roll point
    failed = Signal(str)

    def __init__(self, link, speed, *, clock: Callable[[], float] = time.monotonic,
                 tick_ms: int = 100, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self._speed = speed
        self._clock = clock
        self._phase = Phase.IDLE
        self._deadline: float | None = None
        self._seen_running = False

        self.event_t: float | None = None
        self.stop_t: float | None = None
        self.preroll = 0.0
        self.seek_speed = 1.0
        self.playback_speed = 1.0

        link.stateChanged.connect(self._on_state)
        link.message.connect(self._on_message)
        link.connectedChanged.connect(self._on_connected)
        speed.reached.connect(self._on_speed_reached)
        speed.failed.connect(self._on_speed_failed)
        self._timer = QTimer(self)
        self._timer.setInterval(tick_ms)
        self._timer.timeout.connect(self.tick)
        if tick_ms > 0:
            self._timer.start()

    # --- public -----------------------------------------------------------------------
    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def busy(self) -> bool:
        return self._phase not in (Phase.IDLE, Phase.READY)

    def seek(self, event_t: float, *, preroll: float = 0.0, seek_speed: float = 1.0,
             playback_speed: float = 1.0) -> None:
        """Start a seek. Raises SeekError if it cannot start."""
        s = self._link.state
        if not self._link.connected or s is None:
            raise SeekError("not connected to DCS")
        if preroll < 0:
            raise SeekError("the pre-roll cannot be negative")
        stop_t = event_t - preroll
        now = self._link.model_time_now() or s.t
        if stop_t <= now + MIN_LEAD_S:
            raise SeekError(f"the pre-roll point {stop_t:.2f} s is behind the replay ({now:.2f} s); "
                            "replays only run forward")
        if self.busy:
            self._abort()
        self.event_t, self.stop_t = event_t, stop_t
        self.preroll = preroll
        self.seek_speed, self.playback_speed = seek_speed, playback_speed
        if s.paused:
            self._start_speeding()
        else:
            self._set_phase(Phase.PAUSING)
            self._link.pause()

    def play(self) -> None:
        """Resume; from READY, the seek is done."""
        if self._phase is Phase.READY:
            self._set_phase(Phase.IDLE)
        self._link.resume()

    def cancel(self) -> None:
        if self._phase is Phase.IDLE:
            return
        self._abort()
        self._link.pause()
        self._set_phase(Phase.IDLE)

    def tick(self) -> None:
        if self._deadline is not None and self._clock() > self._deadline:
            what = {Phase.PAUSING: "pause", Phase.ARMING: "arm the stop"}.get(self._phase, "answer")
            self._fail(f"DCS did not {what} in time")

    # --- transitions ------------------------------------------------------------------
    def _set_phase(self, phase: Phase) -> None:
        self._phase = phase
        waits = (Phase.PAUSING, Phase.ARMING)
        self._deadline = self._clock() + CONFIRM_TIMEOUT_S if phase in waits else None
        self.phaseChanged.emit(phase)

    def _abort(self) -> None:
        if self._speed.busy:
            self._speed.cancel()
        if self._phase in (Phase.ARMING, Phase.RUNNING):
            self._link.disarm()

    def _fail(self, message: str) -> None:
        self._abort()
        self._link.pause()
        self._set_phase(Phase.IDLE)
        self.failed.emit(message)

    def _start_speeding(self) -> None:
        s = self._link.state
        if s is not None and self.stop_t is not None and self.stop_t <= s.t + MIN_LEAD_S:
            self._fail(f"the replay passed the pre-roll point ({self.stop_t:.2f} s) while pausing")
            return
        self._set_phase(Phase.SPEEDING)
        self._speed.set_target(self.seek_speed)  # may report reached at once

    # --- events -----------------------------------------------------------------------
    def _on_connected(self, connected: bool) -> None:
        if not connected and self._phase not in (Phase.IDLE, Phase.READY):
            if self._speed.busy:
                self._speed.cancel()
            self._set_phase(Phase.IDLE)
            self.failed.emit("lost the connection to DCS")

    def _on_state(self, s: State) -> None:
        if self._phase is Phase.PAUSING and s.paused:
            self._start_speeding()
        elif self._phase is Phase.RUNNING:
            if not s.paused:
                self._seen_running = True
            elif self._seen_running:
                # Paused, but not by our stop (ARRIVED comes before the STATE that shows it).
                self._fail("the replay was paused before reaching the target")
        elif self._phase is Phase.READY and not s.paused:
            self._set_phase(Phase.IDLE)  # resumed from DCS itself

    def _on_speed_reached(self, speed: float) -> None:
        if self._phase is Phase.SPEEDING:
            self._set_phase(Phase.ARMING)
            self._link.arm_stop(self.stop_t)
        elif self._phase is Phase.SLOWING:
            self._set_phase(Phase.READY)
            self.ready.emit(self.event_t, self.stop_t)

    def _on_speed_failed(self, message: str) -> None:
        if self._phase in (Phase.SPEEDING, Phase.SLOWING):
            self._fail(f"could not set the speed: {message}")

    def _on_message(self, msg: Message) -> None:
        phase = self._phase
        if isinstance(msg, Armed):
            if phase is Phase.ARMING and abs(msg.target - self.stop_t) < 1e-3:
                self._resume_to(Phase.RUNNING)
        elif isinstance(msg, Arrived):
            if phase is Phase.RUNNING and abs(msg.target - self.stop_t) < 1e-3:
                self._set_phase(Phase.SLOWING)
                self._speed.set_target(self.playback_speed)
        elif isinstance(msg, Error) and phase is Phase.ARMING:
            if msg.text.startswith("behind"):
                self._fail("the replay is already past the target")
            else:
                self._fail(f"DCS refused the stop: {msg.text}")
        elif isinstance(msg, Disarmed) and msg.reason != "request" and phase in (Phase.ARMING, Phase.RUNNING):
            reason = {"restart": "the track restarted", "mission_end": "the mission ended"}.get(
                msg.reason, msg.reason)
            self._set_phase(Phase.IDLE)
            self.failed.emit(f"seek stopped: {reason}")

    def _resume_to(self, phase: Phase) -> None:
        self._seen_running = False
        self._set_phase(phase)
        self._link.resume()
