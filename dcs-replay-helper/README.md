# DCS Replay Helper

A desktop helper that drives a DCS track replay that is already running.

- Play and pause the replay.
- Jump forward to a moment you picked beforehand in Tacview: a bookmark or event from the `.acmi` file. The jump uses a speed cap, for example at most 4x.
- Stop with a pre-roll before the event, plus an optional post-roll stop after it.

The app talks over localhost UDP to a small hook script in `Saved Games\DCS\Scripts\Hooks`. The hook reports the replay clock and pauses DCS on the exact frame a target time is reached: 0.002 s late at 1x and 0.015 s at 4x in testing. Time acceleration is driven by the app sending DCS's own keys (`LCtrl+Z` / `LAlt+Z` / `LShift+Z`), because DCS gives Lua no way to set it. See [SPIKE.md](SPIKE.md) for how that was established.

## Status

**Milestone 5 of 6: time sync.**
- **Done:**
  - The window shows the connection, the model clock and mission time of day, and the commanded and measured speed. It has Play/Pause.
  - **Seek:** enter a target in replay time (`1:07.95`, `67.95`) or mission time (`16:31:07`), and set a pre-roll and an optional post-roll.
    - The app pauses, sets the **Seek at** speed while paused, and arms a stop at the target minus the pre-roll.
    - It plays to the stop, then sets the **Playback** speed while still paused.
    - With a post-roll set, **Play through** then plays past the target and pauses that long after it.
    - Targets behind the replay are refused, because replays only run forward.
    - If something unexpected happens mid-seek, the seek stops, the replay is left paused, and the reason is shown. That covers the track restarting, a pause from DCS, a lost connection, or DCS not answering.
  - **Speed:** set by pressing one key at a time and waiting for DCS to confirm each step. A missed key is retried up to 3 times.
    - **Seek at** is also the speed limit: if the replay ever runs faster, it's paused and brought back down.
  - **Tacview events:** open a `.acmi`, `.zip.acmi` or `.txt.acmi` recording to list its events beside the controls.
    - The list holds bookmarks you added in Tacview, Tacview's own events, and three kinds worked out from the recording:
      - **launch salvos:** missiles, rockets and bombs, for example `AGR_20A ×7`
      - **units lost:** an aircraft, ground unit or ship that disappears without leaving the area
      - **ejections**
    - Filter by kind, or search labels and units.
    - Double-click an event, or select it and click **Go to event**, to seek there with the Seek panel's pre-roll and post-roll.
    - Events whose pre-roll point is already behind the replay are grayed out.
    - Large recordings load in the background: about 4 s for 200 MB of uncompressed data.
  - **Time sync:** replay time = Tacview time + offset.
    - Tacview counts from its ReferenceTime, which is UTC. DCS counts from mission start, which is local time on the map.
    - The app works out the time zone by rounding the difference between the two start times to 15 minutes. For the sample that's UTC+4 on Caucasus, so the offset is 0.
    - A recording started after the mission keeps the remainder as its offset.
    - The mission start comes from DCS once connected. Before that, **Open track…** reads it from the `.trk` you are about to replay, along with the date, map and length.
    - You can override the time zone, and add a fine adjustment in seconds.
    - **Sync to selected event** sets the fine adjustment for you: pause DCS on the moment the selected event happens, then click.
    - The offset is saved per recording.
    - A Tacview date more than a day away from the mission date shows a warning.
- **Not built yet:** hook installer, settings for the speed and roll defaults, and a packaged exe (milestone 6).

## Use with DCS

1. Copy `hook/ReplayHelper.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`.
   - Use `DCS.openbeta` if that's your folder.
   - Remove `ReplayHelperSpike.lua` from there if it's still installed, because both use the same ports.
2. Restart DCS. `Logs\dcs.log` should contain `REPLAYHELPER (Main): loaded 0.1.0 (callbacks registered)`.
3. Start the app from this folder with `uv run replay-helper`. On Windows `uv` picks up Python from the repo's `.python-version`.
4. Play a track in DCS. The app connects within a second.
5. Type a time under **Seek**, set the pre-roll and post-roll, and click **Go**. To change speed, the app brings the DCS window to the front to press the keys, so DCS must not be minimised.
6. Or click **Open Tacview recording…** and double-click a bookmark. You can also start the app with the recording, and optionally its track: `uv run replay-helper recording.zip.acmi track.trk`.
7. If an event lands early or late, pause DCS on the moment it happens, select it in the list, and click **Sync to selected event**.

## Development

```
cd dcs-replay-helper
uv run pytest                      # hook (Lua 5.1 via lupa), protocol, link, fake DCS, window
uv run python tools/fake_dcs.py    # a stand-in for DCS + hook, on the same ports
uv run replay-helper               # in a second terminal
```

The fake DCS simulates the replay clock, pause and stop. In place of keystrokes it accepts `KEY UP|DOWN|NORMAL` commands, using the same speed ladder DCS showed: +1x per step above 1x, halving below it.

The window tests run headless (`QT_QPA_PLATFORM=offscreen`). They skip on Linux machines without `libEGL`.

## Layout

```
hook/ReplayHelper.lua              # the DCS hook (install into Saved Games\DCS\Scripts\Hooks)
hook/spike/ReplayHelperSpike.lua   # milestone 0 probe hook, kept for reference
src/replay_helper/
  dcs/protocol.py                  # the UDP line protocol (see the hook's header)
  dcs/link.py                      # Qt UDP link, connection watchdog, clock interpolation
  dcs/keys.py                      # LCtrl/LAlt/LShift+Z as scan codes to the DCS window (Windows)
  dcs/speed.py                     # closed-loop speed controller and speed limit
  dcs/trk.py                       # mission start, date, map and length from a .trk
  seek.py                          # seek state machine: pause, speed, arm, run, slow, post-roll
  tacview/acmi.py                  # streaming ACMI 2.x reader (objects and events, no positions)
  tacview/events.py                # seekable events: bookmarks, launches, losses, ejections, ...
  ui/event_table.py                # event list: load, filter, gray out the past, pick
  ui/main_window.py                # main window
  timefmt.py                       # time formatting and parsing
  timesync.py                      # Tacview time -> replay time: auto time zone, fine, sync
  settings.py                      # JSON settings (per-recording sync) in %APPDATA%
  app.py                           # entry point (replay-helper / python -m replay_helper)
tools/fake_dcs.py                  # DCS + hook simulator for development
tools/spike_client.py              # console client for the spike hook
tests/                             # pytest; lua_harness.py mocks the DCS hooks environment
tests/data/                        # a real DCS track and its Tacview recording, with two bookmarks
```
