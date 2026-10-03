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
   `REPLAYHELPER (Main): loaded spike-3 (callbacks registered)`
3. In a terminal, from the `dcs-replay-helper` folder, run `python tools\spike_client.py`. It needs Python 3.10 or newer and no packages. It writes everything to `spike_session.log` in the current folder.
4. In DCS, play the sample track `LastMissionTrack.trk`. Within a second the client should print `HELLO spike-3`. Typing `s` then shows the live `STATE` line.

## Round 3: find the command ids, then get above 1x (current)

Round 2's `find` showed that the three time-acceleration commands (`iCommandAccelerate`, `iCommandDecelerate`, `iCommandNoAcceleration`) are bound in `Config\Input\UiLayer\joystick\default.lua`, but no Lua file assigns them numbers. DCS supplies the numbers itself as Lua globals, so `spike-3` looks for them in each Lua state instead of in files.

Replace the hook in `Scripts\Hooks` with the new `ReplayHelperSpike.lua`, restart DCS, play `LastMissionTrack.trk`, and start the client.

| # | Do | Look for |
|---|----|----------|
| 1 | `globals` | `GLOBALS <state> iCommandAccelerate=<n> …` in one of the lines (`hooks`, `config`, `mission`, `export`, `server`). If every line says `(none)`, try `globals icommand`. That lists every iCommand it can see, capped at 60. |
| 2 | If you got numbers: `cmd <accelerate n>`, wait 2 s, then `cmd <accelerate n>` again | `LOCMD-AFTER … accel=2.000`, then `accel=4.000`. If nothing changes, try `digital <accelerate n>` twice the same way. Finish with `cmd <normal n>` or `digital <normal n>` for 1x. |
| 3 | Either way: `key normal`, then `key up` three times | After each key, the client prints the STATE line. Check whether `accel=` goes 2 → 4 → 8. Click into DCS during the 3 s countdown if focusing fails. |
| 4 | `key normal`, `s` to read `t=`, `arm <t + 40>`, then get to 4x with whatever worked in 2 or 3 | `ARRIVED … over=…` with `over` below about 0.1, and DCS paused. |
| 5 | `q` | Upload `spike_session.log`. |

## Round 2: speed above 1x (done: no numeric ids in Lua files)

Round 1 confirmed pause/resume, the clock, the mission start time and a stop at 1x landing within 0.002 s. Keystrokes could slow the replay down and bring it back to 1x, but **nothing ever went above 1x**, and `find` / `cmd` were never run. The probe showed that `Export.LoSetCommand` and `Export.LoGetModelTimeAcceleration` are reachable from the hook, so the hook may be able to change speed itself, with no window focus needed.

`spike-2` adds `accel=` to every STATE line: the speed DCS says it is commanding, next to the measured `speed=`. After each `cmd`, it prints a `LOCMD-AFTER` line about half a second later showing the effect.

Replace the hook file in `Scripts\Hooks` with the new `ReplayHelperSpike.lua`, then restart DCS and play `LastMissionTrack.trk` again.

| # | Do | Look for |
|---|----|----------|
| 1 | `p`, then `find`, then `r` | `CMDID iCommand…=<number>` lines. Note the numbers for accelerate, decelerate and normal speed (no acceleration). If no line has a number, try `find Mods` instead. |
| 2 | `cmd <accelerate id>`, wait 2 s, then run it again | `LOCMD-AFTER … accel=2.000`, then `accel=4.000`. Type `s` to see whether the measured `speed=` follows. |
| 3 | `cmd <normal id>` | `accel=1.000`. |
| 4 | Only if `cmd` did nothing: `key up`, twice | Whether keystrokes can get above 1x, now that `accel=` shows it directly. |
| 5 | `s` to read `t=`, then `arm <t + 30>`, then speed up to 4x with whatever worked in 2 or 4 | `ARRIVED … over=…` with `over` below about 0.1, and DCS paused. |
| 6 | `q` | Upload `spike_session.log`. |

## Round 1 tests (done)

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
