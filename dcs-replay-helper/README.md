# DCS Replay Helper

A desktop helper that drives a DCS track replay that's already running. Plan your shots in Tacview, then let the app take the replay there.

- **Pick a moment:** a bookmark or event from the Tacview recording (`.acmi`), or a time you type in.
- **Jump forward to it under a speed cap**, for example at most 4x. Replays can only run forward, and fast acceleration can desync them.
- **Stop with a pre-roll** a few seconds before the event, and optionally a **post-roll** just after it.

The app talks over localhost UDP to a small hook script in `Saved Games\DCS\Scripts\Hooks`. The hook reports the replay clock and pauses DCS on the exact frame a target is reached: 0.002 s late at 1x and 0.015 s at 4x in testing.

DCS gives Lua no way to set time acceleration. So the app presses DCS's own keys (`LCtrl+Z` up, `LAlt+Z` down, `LShift+Z` back to 1x) one at a time, and checks each step against the speed DCS reports. [SPIKE.md](SPIKE.md) shows how that was established.

## Install

1. Download `DCSReplayHelper.exe` from this repository's [Releases](https://github.com/nicelifeBS/dcs-tools/releases) (tags `replay-helper-v*`), or build it yourself (see Development).
2. Run it and choose **Tools → Install / update DCS hook…**.
   - The app finds your `Saved Games\DCS*` folders and puts `ReplayHelper.lua` into `Scripts\Hooks`. Nothing is written to the DCS install folder.
   - It also removes the old spike hook, `ReplayHelperSpike.lua`, if it's there, because the two would clash.
3. Restart DCS. The app's log says at startup whether the hook is installed and current.

## Use

1. **Connect:** play a track in DCS. The app connects within a second and shows the replay clock and the mission time of day.
2. **Load your Tacview recording:** **File → Open Tacview recording…**, or `DCSReplayHelper.exe recording.zip.acmi [track.trk]`. Its bookmarks are listed on the right.
   - Tick **Launches**, **Kills**, **Ejections** and so on to see events the app works out from the recording. There's also a search box.
3. **Check the time sync** box above the list. It should read for example "time zone UTC+4:00 (auto) · replay time = Tacview time +0.00 s".
   - Tacview times are UTC and the mission clock is local map time. The app works out the difference.
   - **Open track…** checks this before DCS is running.
4. **Set the seek options:** set **Pre-roll** (default 5 s) and, if you want, **Post-roll**. **Seek at** is the speed for jumping, and also the most the replay is ever allowed to run. **Playback** is the speed to watch at.
5. **Seek:** double-click a bookmark, or select it and click **Go to event**.
   - The app pauses, sets the seek speed while paused, runs to the pre-roll point, and pauses there at playback speed.
   - Press **Play** (or **Play through**, with a post-roll) to roll.
   - You can also type a time under **Seek**, in replay time (`1:07.95`) or mission time (`16:31:07`).
6. **Fix an event that lands early or late:** pause DCS exactly when it happens, select it, and click **Sync to selected event**. The correction is saved for that recording.

**Keystrokes:** to press the speed keys, the app brings the DCS window to the front, so DCS must not be minimised.

**What is remembered:** speeds, pre-roll and post-roll, filters, the last folders used, and the window layout. They're kept in `%APPDATA%\dcs-replay-helper\settings.json`.

## How it works

- **Hook (`src/replay_helper/hook/ReplayHelper.lua`):**
  - Sends `STATE` about 10 times a second: model time, measured and commanded speed, pause, armed stop, and mission start, date and map.
  - Takes `PAUSE`, `RESUME`, `ARMSTOP <t>` and `DISARM`.
  - Checks the armed stop every frame and pauses on the first frame at or past it.
  - Refuses stops behind the replay, and drops a stop if the track restarts or the mission ends.
- **Speed:** keys are pressed one at a time. Each step waits for DCS to report the new speed, and a missed key is retried up to 3 times.
  - Above 1x, each step adds 1x. Below 1x, it halves. Going down from above 1x is done as "back to 1x" then up.
  - If the replay ever runs faster than **Seek at**, it's paused and brought back down.
- **Seek:** pause, set the seek speed (while paused), arm the stop, resume, then set the playback speed on arrival (still paused).
  - Anything unexpected ends the seek with a reason and leaves the replay paused: the track restarting, a pause from DCS, a lost connection, or DCS not confirming a step.
- **Tacview:** ACMI 2.x recordings are streamed, and positions are skipped without being parsed. About 4.5 s for 200 MB of uncompressed data.
  - Bookmarks you add in Tacview are stored in the file and listed by name.
  - Launches are grouped into salvos, units that disappear without leaving the area count as lost, and `PILOT_*` objects mark ejections.
- **Time sync:** replay time = Tacview time + offset, where offset = (ReferenceTime + time zone) − mission start + fine adjustment. The time zone is rounded to 15 minutes, and both it and the fine adjustment can be overridden.

## Development

```
cd dcs-replay-helper
uv run pytest                                          # 237 tests: hook (Lua 5.1 via lupa), protocol, link,
                                                       # speed, seek, Tacview, time sync, installer, window
uv run python tools/fake_dcs.py                        # a stand-in for DCS + hook, on the same ports
uv run replay-helper                                   # the app, in a second terminal
uv run --group build pyinstaller replay_helper.spec    # dist/DCSReplayHelper.exe (on Windows)
```

The fake DCS simulates the replay clock, pause and stop. In place of keystrokes it accepts `KEY UP|DOWN|NORMAL` commands, using the speed steps DCS showed.

The window tests run headless (`QT_QPA_PLATFORM=offscreen`). They skip on Linux machines without `libEGL`.

The GitHub workflow `.github/workflows/replay-helper.yml` runs the tests on Linux and Windows and builds the exe.
To release, put the notes in `release-notes/<version>.md`, set `__version__` in `src/replay_helper/__init__.py`, and run *DCS Replay Helper release* from the Actions tab with that version. It publishes the exe as the release's only file, tagged `replay-helper-v<version>`.

## Layout

```
src/replay_helper/
  hook/ReplayHelper.lua            # the DCS hook (installed by Tools > Install / update DCS hook)
  hook_installer.py                # find Saved Games\DCS*, install/update the hook, remove the spike
  dcs/protocol.py                  # the UDP line protocol (see the hook's header)
  dcs/link.py                      # Qt UDP link, connection watchdog, clock interpolation
  dcs/keys.py                      # LCtrl/LAlt/LShift+Z as scan codes to the DCS window (Windows)
  dcs/speed.py                     # closed-loop speed controller and speed limit
  dcs/trk.py                       # mission start, date, map and length from a .trk
  seek.py                          # seek state machine: pause, speed, arm, run, slow, post-roll
  tacview/acmi.py                  # streaming ACMI 2.x reader (objects and events, no positions)
  tacview/events.py                # seekable events: bookmarks, launches, losses, ejections, ...
  timesync.py                      # Tacview time -> replay time: auto time zone, fine, sync
  settings.py                      # JSON settings in %APPDATA%\dcs-replay-helper
  ui/main_window.py                # main window, menus, remembered settings
  ui/event_table.py                # event list and time sync panel
  timefmt.py                       # time formatting and parsing
  app.py                           # entry point (replay-helper / python -m replay_helper)
replay_helper.spec                 # PyInstaller build of DCSReplayHelper.exe
hook/spike/ReplayHelperSpike.lua   # milestone 0 probe hook, kept for reference (see SPIKE.md)
tools/fake_dcs.py                  # DCS + hook simulator for development
tools/spike_client.py              # console client for the spike hook
tests/                             # pytest; lua_harness.py mocks the DCS hooks environment
tests/data/                        # a real DCS track and its Tacview recording, with two bookmarks
```
