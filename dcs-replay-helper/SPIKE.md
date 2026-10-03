# Milestone 0 spike: what can a hook do during a replay?

The spike has two parts: a throwaway DCS hook and a console client. Running them once tells us how the real hook has to work:

1. Can the hook pause, resume and read the clock during a `.trk` replay?
2. Can it change time acceleration itself (`LoSetCommand`), or does the app have to press `Ctrl+Z` / `Alt+Z` / `Shift+Z` in the DCS window?
3. Where is the mission start time, and does DCS model time line up with Tacview time?
4. How precisely does a hook-side stop land at 4x?

Nothing is written to the DCS install folder. The hook only logs and answers on localhost UDP ports 47810 and 47811.

## Setup

1. Copy `hook/spike/ReplayHelperSpike.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`. Create the `Hooks` folder if it doesn't exist, and use `DCS.openbeta` instead of `DCS` if that's your Saved Games folder.
2. Start DCS. `Saved Games\DCS\Logs\dcs.log` should contain:
   `REPLAYHELPER (Main): loaded spike-1 (callbacks registered)`
3. In a terminal, from the `dcs-replay-helper` folder, run `python tools\spike_client.py`. It needs Python 3.10 or newer and no packages. It writes everything to `spike_session.log` in the current folder.
4. In DCS, play the sample track `LastMissionTrack.trk`. Within a second the client should print `HELLO spike-1`. Typing `s` then shows the live `STATE` line.

## Tests

Type these at the client's `>` prompt. Results print as they arrive and are saved to the session log.

| # | Do | Look for |
|---|----|----------|
| 1 | `probe` | A `PROBE begin` … `PROBE end` block. The block reports which `DCS.*` functions exist, whether `LoSetCommand` and `Export` are reachable, the mission start time (expected `start_time=59400`, which is 16:30), and what `net.dostring_in` returns in each Lua state. |
| 2 | `p`, then `s` | DCS pauses and `paused=true`. Type `r` to resume and check that `paused=false`. |
| 3 | `p`, then `find`, then `r` | `CMDID iCommand…=<number>` lines for accelerate, decelerate and normal speed. If none have a number, try `find Mods\aircraft\A-10C_2`, or any other folder under the DCS install. The scan can freeze DCS for a moment, which is why you pause first. |
| 4 | `w` (watch on), then `cmd <accelerate id>` | Whether `speed=` goes from 1 to 2 within a second or two. Repeat the command to see each step (2, 4, 8, …). Then try `cmd <decelerate id>` and `cmd <normal id>`. |
| 5 | Only if test 4 did nothing: `cmdx <accelerate id>` | The same check, run in the export Lua state. |
| 6 | `key up`, `key down`, `key normal` | Keystroke fallback. It focuses DCS and presses LCtrl+Z, LAlt+Z or LShift+Z. If focusing fails, click into DCS within 3 s. Note whether `speed=` changes. Also press the keys yourself and note the speeds DCS shows for each step. |
| 7 | Speed up, then `p`, then `r` | Whether the speed is kept after pause and resume, or drops back to 1x. |
| 8 | Restart the track from the start. While the clock is under 60 s, run `arm 62.95`, then speed up to 4x with whichever method worked | `ARRIVED t=… over=…` with `over` below about 0.1, DCS paused, and the in-game clock (F10 map, or the HUD time if shown) at 16:31:02–03. |
| 9 | `arm 67.95`, then `r` at 1x | Pauses at the Tacview bookmark `Running in`. Does the picture match the moment you bookmarked in Tacview? |
| 10 | `w` (watch off), then `q` | Ends the session. |

## Send back

- `spike_session.log`
- The `REPLAYHELPER` lines from `dcs.log`, for example from:
  `findstr REPLAYHELPER "%USERPROFILE%\Saved Games\DCS\Logs\dcs.log" > replayhelper.txt`
- Short notes on tests 4–9: which speed method worked, the speed steps you saw, whether speed survives a pause, and whether the stop landed on the right moment.

Delete `ReplayHelperSpike.lua` from `Scripts\Hooks` afterwards. The real hook replaces it.
