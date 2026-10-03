# DCS Replay Helper

A desktop helper that drives a DCS track replay that is already running.

- Play and pause the replay.
- Jump forward to a moment you picked beforehand in Tacview: a bookmark or event from the `.acmi` file. The jump uses a speed cap, for example at most 4x.
- Stop with a pre-roll before the event, plus an optional post-roll stop after it.

The app talks over localhost UDP to a small hook script in `Saved Games\DCS\Scripts\Hooks`. The hook reports the replay clock and pauses DCS on the exact frame a target time is reached: 0.002 s late at 1x and 0.015 s at 4x in testing. Time acceleration is driven by the app sending DCS's own keys (`LCtrl+Z` / `LAlt+Z` / `LShift+Z`), because DCS gives Lua no way to set it. See [SPIKE.md](SPIKE.md) for how that was established.

## Status

**Milestone 4 of 6: Tacview events.**
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
- **Not built yet:** time sync (milestone 5).
  - For now, Tacview time is taken as replay time. That holds when the Tacview recording started with the mission, as in `tests/data`.
  - Milestone 5 adds the automatic time-zone offset, manual offsets and "sync to this event".

## Use with DCS

1. Copy `hook/ReplayHelper.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`.
   - Use `DCS.openbeta` if that's your folder.
   - Remove `ReplayHelperSpike.lua` from there if it's still installed, because both use the same ports.
2. Restart DCS. `Logs\dcs.log` should contain `REPLAYHELPER (Main): loaded 0.1.0 (callbacks registered)`.
3. Start the app from this folder with `uv run replay-helper`. On Windows `uv` picks up Python from the repo's `.python-version`.
4. Play a track in DCS. The app connects within a second.
5. Type a time under **Seek**, set the pre-roll and post-roll, and click **Go**. To change speed, the app brings the DCS window to the front to press the keys, so DCS must not be minimised.
6. Or click **Open Tacview recording…** (or start the app with `uv run replay-helper path\to\recording.zip.acmi`) and double-click a bookmark.

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
  seek.py                          # seek state machine: pause, speed, arm, run, slow, post-roll
  tacview/acmi.py                  # streaming ACMI 2.x reader (objects and events, no positions)
  tacview/events.py                # seekable events: bookmarks, launches, losses, ejections, ...
  ui/event_table.py                # event list: load, filter, gray out the past, pick
  ui/main_window.py                # main window
  timefmt.py                       # time formatting
  app.py                           # entry point (replay-helper / python -m replay_helper)
tools/fake_dcs.py                  # DCS + hook simulator for development
tools/spike_client.py              # console client for the spike hook
tests/                             # pytest; lua_harness.py mocks the DCS hooks environment
tests/data/                        # a real DCS track and its Tacview recording, with two bookmarks
```
