"""A stand-in for DCS + hook/ReplayHelper.lua, for developing the app without DCS.

Speaks the hook's UDP protocol on the same ports and simulates a replay: a model clock that
runs at the commanded time acceleration, pause, and a stop checked every frame. Standard
library only.

    uv run python tools/fake_dcs.py [--start 0] [--duration 117.1] [--paused]

Real DCS changes speed through keystrokes sent to its window. The fake has no window, so it
takes the same steps as extra commands instead: KEY UP | KEY DOWN | KEY NORMAL (LCtrl+Z /
LAlt+Z / LShift+Z). The speed ladder matches what DCS showed in the spike: above 1x each
step up adds 1x; below 1x the steps halve.
"""

from __future__ import annotations

import argparse
import socket
import time

VERSION = "fake-0.1.0"
HOST = "127.0.0.1"
STATE_PORT = 47810
CMD_PORT = 47811
STATE_INTERVAL = 0.1
MIN_ACCEL = 1 / 16
MAX_ACCEL = 64.0


def accel_up(a: float) -> float:
    return min(a * 2 if a < 1 else a + 1, MAX_ACCEL)


def accel_down(a: float) -> float:
    # Below and at 1x DCS halves (seen in the spike). Above 1x stepping down by 1 is assumed.
    return max(a / 2 if a <= 1 else a - 1, MIN_ACCEL)


class FakeDcs:
    """The simulation, without any networking: feed it commands and frames, collect output."""

    def __init__(
        self,
        *,
        start: float = 0.0,
        duration: float | None = None,
        paused: bool = False,
        start_tod: float = 59400.0,
        date: str = "2018-02-01",
        theatre: str = "Caucasus",
    ) -> None:
        self.t = start
        self.rt = 0.0
        self.accel = 1.0
        self.paused = paused
        self.duration = duration
        self.stop: float | None = None
        self.start_tod = start_tod
        self.date = date
        self.theatre = theatre
        self.outbox: list[str] = [f"HELLO {VERSION}"]
        self._next_state = 0.0

    def state_line(self) -> str:
        speed = 0.0 if self.paused else self.accel
        return (
            f"STATE t={self.t:.3f} rt={self.rt:.3f} speed={speed:.3f} accel={self.accel:.3f} "
            f"paused={str(self.paused).lower()} track=true "
            f"stop={self.stop if self.stop is not None else -1:.3f} start_tod={self.start_tod:.3f} "
            f"date={self.date} theatre={self.theatre}"
        )

    def handle(self, line: str) -> None:
        parts = line.strip().split()
        if not parts:
            return
        word, args = parts[0].upper(), parts[1:]
        if word == "PING":
            self.outbox.append(f"PONG {VERSION}")
        elif word == "PAUSE":
            self.paused = True
        elif word == "RESUME":
            if self.duration is None or self.t < self.duration:
                self.paused = False
        elif word == "ARMSTOP":
            try:
                target = float(args[0]) if len(args) == 1 else None
            except ValueError:
                target = None
            if target is None:
                self.outbox.append("ERR ARMSTOP needs a model time")
            elif target <= self.t:
                self.outbox.append(f"ERR behind target={target:.3f} now={self.t:.3f}")
            else:
                self.stop = target
                self.outbox.append(f"ARMED target={target:.3f} now={self.t:.3f}")
        elif word == "DISARM":
            self.stop = None
            self.outbox.append("DISARMED reason=request")
        elif word == "KEY" and args:
            step = args[0].upper()
            if step == "UP":
                self.accel = accel_up(self.accel)
            elif step == "DOWN":
                self.accel = accel_down(self.accel)
            elif step == "NORMAL":
                self.accel = 1.0
        else:
            self.outbox.append(f"ERR unknown command {parts[0]}")

    def frame(self, dt: float) -> None:
        """Advance one frame of `dt` real seconds."""
        self.rt += dt
        if not self.paused:
            self.t += dt * self.accel
            if self.stop is not None and self.t >= self.stop:
                target, self.stop = self.stop, None
                self.paused = True
                self.outbox.append(f"ARRIVED t={self.t:.3f} target={target:.3f} over={self.t - target:.3f}")
            if self.duration is not None and self.t >= self.duration:
                self.t = self.duration
                self.paused = True  # DCS pauses at the end of a track
        if self.rt >= self._next_state:
            self._next_state = self.rt + STATE_INTERVAL
            self.outbox.append(self.state_line())

    def drain(self) -> list[str]:
        out, self.outbox = self.outbox, []
        return out


def serve(sim: FakeDcs, *, fps: float = 60.0, state_port: int = STATE_PORT, cmd_port: int = CMD_PORT,
          should_stop=lambda: False, quiet: bool = False) -> None:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind((HOST, cmd_port))
    rx.setblocking(False)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dt = 1.0 / fps
    last = time.monotonic()
    try:
        while not should_stop():
            while True:
                try:
                    data, _ = rx.recvfrom(4096)
                except BlockingIOError:
                    break
                line = data.decode("utf-8", errors="replace")
                if not quiet:
                    print(f"<< {line}")
                sim.handle(line)
            now = time.monotonic()
            sim.frame(now - last)
            last = now
            for line in sim.drain():
                tx.sendto(line.encode("utf-8"), (HOST, state_port))
                if not quiet and not line.startswith("STATE "):
                    print(f">> {line}")
            time.sleep(dt)
    finally:
        rx.close()
        tx.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", type=float, default=0.0, help="model time to start at")
    ap.add_argument("--duration", type=float, default=117.1, help="track length; pauses there (0 = endless)")
    ap.add_argument("--paused", action="store_true", help="start paused")
    ap.add_argument("--fps", type=float, default=60.0)
    args = ap.parse_args()
    sim = FakeDcs(start=args.start, duration=args.duration or None, paused=args.paused)
    print(f"fake DCS on {HOST}: state -> :{STATE_PORT}, commands <- :{CMD_PORT}  (Ctrl+C to quit)")
    try:
        serve(sim, fps=args.fps)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
