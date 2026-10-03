# DCS Replay Helper

A desktop helper that drives a DCS track replay that is already running.

- Play and pause the replay.
- Jump forward to a moment you picked beforehand in Tacview: a bookmark or event from the `.acmi` file. The jump uses a speed cap, for example at most 4x.
- Stop with a pre-roll before the event, plus an optional post-roll stop after it.

The app talks over localhost UDP to a small hook script in `Saved Games\DCS\Scripts\Hooks`. The hook reports the replay clock and pauses DCS on the exact frame a target time is reached: 0.002 s late at 1x and 0.015 s at 4x in testing. Time acceleration is driven by the app sending DCS's own keys (`LCtrl+Z` / `LAlt+Z` / `LShift+Z`), because DCS gives Lua no way to set it. See [SPIKE.md](SPIKE.md) for how that was established.

## Status

**Milestone 1 of 6: hook, link and a bare window.**
- **Done:** the window shows the connection, the model clock and mission time of day, and the commanded and measured speed. It has Play/Pause, and a manual "pause at model time" stop.
- **Not built yet:** speed control from the app (milestone 2), seeking with pre-roll and post-roll (milestone 3), and the Tacview bookmarks (milestones 4 and 5).

## Use with DCS

1. Copy `hook/ReplayHelper.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`.
   - Use `DCS.openbeta` if that's your folder.
   - Remove `ReplayHelperSpike.lua` from there if it's still installed, because both use the same ports.
2. Restart DCS. `Logs\dcs.log` should contain `REPLAYHELPER (Main): loaded 0.1.0 (callbacks registered)`.
3. Start the app from this folder with `uv run replay-helper`. On Windows `uv` picks up Python from the repo's `.python-version`.
4. Play a track in DCS. The app connects within a second.

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
  ui/main_window.py                # main window
  timefmt.py                       # time formatting
  app.py                           # entry point (replay-helper / python -m replay_helper)
tools/fake_dcs.py                  # DCS + hook simulator for development
tools/spike_client.py              # console client for the spike hook
tests/                             # pytest; lua_harness.py mocks the DCS hooks environment
```
