"""A stand-in for DCS + src/replay_helper/hook/ReplayHelper.lua, for developing the app without DCS.

Speaks the hook's UDP protocol on the same ports and simulates a replay: a model clock that
runs at the commanded time acceleration, pause, and a stop checked every frame. Standard
library only.

    uv run python tools/fake_dcs.py [--start 0] [--duration 117.1] [--paused]

Speed steps come as SPEED UP | DOWN | NORMAL, as for hook 0.2.0, or as the older KEY UP |
DOWN | NORMAL (what the app sends when it would press LCtrl+Z / LAlt+Z / LShift+Z). The speed
ladder matches what DCS showed in the spike: above 1x each step up adds 1x; below 1x the
steps halve. FOCUS <id> [name] answers FOCUSED at once for the ids in `aircraft` (all ids
when it is None), FOCUS-FAILED reason=not_found otherwise.
"""

from __future__ import annotations

import argparse
import math
import socket
import time
from urllib.parse import quote

VERSION = "fake-0.3.0"
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


# id -> (kind, type, unit, group, coalition, human, speed m/s along +x, start x, y)
FAKE_OBJECTS = {
    16797696: ("plane", "F-16C_50", "Viper 1-1 | Ace", "Viper 1-1", "blue", True, 200.0, 0.0, 300.0),
    16797952: ("plane", "Su-27", "Flanker 2-1", "Flanker 2-1", "red", False, -180.0, 6000.0, 900.0),
    16798208: ("heli", "Mi-24P", "Hokum 1-1", "Hokum 1-1", "red", False, 50.0, 800.0, -400.0),
    16798464: ("weapon", "AIM-120C", "-", "-", "blue", False, 600.0, 200.0, 300.0),
}
KEY_FACTOR, KEY_FIRST, WHEEL_STEP = 1.1, 5.0, 1.13  # the free camera, as measured in DCS


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
        aircraft: set[int] | None = None,
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
        self.aircraft = aircraft
        self.focused: int | None = None
        self.track = False  # TRACK on
        self.watched: int | None = None
        self.camv = 0.0  # free camera speed along +x, m/s; keys and wheel change it
        self.cam_x = -50.0
        self.outbox: list[str] = [f"HELLO {VERSION}"]
        self.max_running_accel = 0.0  # fastest speed the replay actually ran at (for tests)
        self._next_state = 0.0

    def object_x(self, oid: int) -> float:
        o = FAKE_OBJECTS[oid]
        return o[7] + o[6] * self.t

    def object_lines(self, radius: float | None) -> list[str]:
        out = []
        for oid, (kind, typ, unit, group, coal, human, v, _x0, y) in FAKE_OBJECTS.items():
            ahead = self.object_x(oid) - self.cam_x
            dist = math.hypot(ahead, y)
            if radius is not None and dist > radius:
                continue
            known = self.t > 0.5  # a speed needs two samples
            sp = f"{abs(v):.2f}" if known else "-"
            al = f"{v:.2f}" if known else "-"
            enc = lambda x: "-" if x in (None, "") else quote(x, safe="")  # noqa: E731
            out.append(f"OBJ id={oid} kind={kind} type={enc(typ)} unit={enc(unit)} group={enc(group)} "
                       f"coalition={coal} human={str(human).lower()} speed={sp} along={al} side=0.00 "
                       f"dist={dist:.0f} ahead={ahead:.0f} age=0.1")
        out.sort(key=lambda line: float(line.split("dist=")[1].split()[0]))
        out.append(f"OBJ-END count={len(out)} total={len(FAKE_OBJECTS)} t={self.t:.3f}")
        return out

    def state_line(self) -> str:
        speed = 0.0 if self.paused else self.accel
        return (
            f"STATE t={self.t:.3f} rt={self.rt:.3f} speed={speed:.3f} accel={self.accel:.3f} "
            f"paused={str(self.paused).lower()} track=true "
            f"stop={self.stop if self.stop is not None else -1:.3f} start_tod={self.start_tod:.3f} "
            f"date={self.date} theatre={self.theatre} cam={self.camv:.3f}"
            + (f" tgt={self.watched} tgt_along={FAKE_OBJECTS[self.watched][6]:.2f} tgt_side=0.00"
               if self.watched in FAKE_OBJECTS and self.t > 0.5 else
               f" tgt={self.watched} tgt_along=- tgt_side=-" if self.watched is not None else "")
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
        elif word == "FOCUS":
            if not args:
                return
            if not args[0].isdigit():
                self.outbox.append("ERR FOCUS needs a DCS id")
            elif self.aircraft is not None and int(args[0]) not in self.aircraft:
                self.outbox.append(f"FOCUS-FAILED id={args[0]} reason=not_found")
            else:
                self.focused = int(args[0])
                self.outbox.append(f"FOCUSED id={args[0]} steps=1")
        elif word == "TRACK" and args:
            self.track = args[0].lower() == "on"
        elif word == "OBJECTS":
            if not self.track:
                self.outbox.append("ERR OBJECTS needs TRACK on")
            else:
                self.outbox.extend(self.object_lines(float(args[0]) if args else None))
        elif word == "WATCH":
            self.watched = int(args[0]) if args and args[0].isdigit() else None
        elif word == "CAM" and len(args) == 2:
            self.camera_input(args[0].upper(), int(args[1]))
        elif word in ("KEY", "SPEED") and args:
            step = args[0].upper()
            if step == "UP":
                self.accel = accel_up(self.accel)
            elif step == "DOWN":
                self.accel = accel_down(self.accel)
            elif step == "NORMAL":
                self.accel = 1.0
        else:
            self.outbox.append(f"ERR unknown command {parts[0]}")

    def camera_input(self, what: str, n: int) -> None:
        """LAlt+Num* (FASTER) and LAlt+Num/ (SLOWER) press n times: x1.1 and /1.1; the wheel adds
        1.13 m/s per notch (positive: forward). All ignored while paused, as in DCS."""
        if self.paused:
            return
        for _ in range(abs(n)):
            if what == "FASTER":
                self.camv = KEY_FIRST if self.camv < 0.5 else self.camv * KEY_FACTOR
            elif what == "SLOWER":
                self.camv = self.camv / KEY_FACTOR if self.camv > 0 else self.camv
            elif what == "WHEEL":
                self.camv += math.copysign(WHEEL_STEP, n)

    def frame(self, dt: float) -> None:
        """Advance one frame of `dt` real seconds."""
        self.rt += dt
        if not self.paused:
            self.max_running_accel = max(self.max_running_accel, self.accel)
            self.t += dt * self.accel
            self.cam_x += self.camv * dt * self.accel
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
          should_stop=lambda: False, quiet: bool = False, time_scale: float = 1.0,
          on_ready=lambda: None) -> None:
    """Run the simulation in real time; time_scale > 1 runs it faster (for tests)."""
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind((HOST, cmd_port))
    rx.setblocking(False)
    on_ready()
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
            sim.frame((now - last) * time_scale)
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
