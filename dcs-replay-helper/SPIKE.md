# Milestone 0 spike: what can a hook do during a replay?

The spike has two parts: a throwaway DCS hook and a console client. Running them once tells us how the real hook has to work:

1. Can the hook pause, resume and read the clock during a `.trk` replay?
2. Can it change time acceleration itself (`LoSetCommand`), or does the app have to press `Ctrl+Z` / `Alt+Z` / `Shift+Z` in the DCS window?
3. Where is the mission start time, and does DCS model time line up with Tacview time?
4. How precisely does a hook-side stop land at 4x?

Rounds 1–3 answered those. Round 4 asks a new question: can the hook put DCS's F2 view on a given unit, and tell which unit the camera is on?

Nothing is written to the DCS install folder. The hook only logs and answers on localhost UDP ports 47810 and 47811.

## Setup

1. Copy `hook/spike/ReplayHelperSpike.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`. Create the `Hooks` folder if it doesn't exist, and use `DCS.openbeta` instead of `DCS` if that's your Saved Games folder.
2. Start DCS. `Saved Games\DCS\Logs\dcs.log` should contain:
   `REPLAYHELPER (Main): loaded spike-4 (callbacks registered)`
3. In a terminal, from the `dcs-replay-helper` folder, run `python tools\spike_client.py`. It needs Python 3.10 or newer and no packages. It writes everything to `spike_session.log` in the current folder.
4. In DCS, play the sample track `LastMissionTrack.trk`. Within a second the client should print `HELLO spike-4`. Typing `s` then shows the live `STATE` line.

## Results (spike finished)

- **Speed control is keystrokes.** `LCtrl+Z`, `LAlt+Z` and `LShift+Z` are sent as scan codes to the focused DCS window. They work during playback, including while paused.
  - Above 1x, each `LCtrl+Z` adds 1x: 1 → 2 → 3 → 4. Below 1x, `LAlt+Z` halves the speed (0.5, 0.25). `LShift+Z` returns to 1x.
  - `Export.LoGetModelTimeAcceleration()` (`accel=`) reports the new speed immediately, even while paused.
- **No scripted speed command.** The `iCommand*` ids for time acceleration aren't reachable from any Lua state, so `LoSetCommand` / `dispatchDigitalAction` can't be used.
- **Pause and resume** from the hook work. The speed is kept through a pause.
- **The hook's frame-checked stop** landed within 0.002 s at 1x and 0.015 s at 4x.
- **Model time is seconds since mission start.** The mission start time is in `DCS.getCurrentMission().mission.start_time`.

## Round 4: put the F2 view on a unit (to do)

**Goal:** when the app seeks to an event, show the event's aircraft in F2 view. DCS has no call for "view this unit" and none for "which unit is being viewed", so this round tests a workaround:

- **Switch views with `LoSetCommand`.** A community-extracted table of command ids gives `iCommandViewAir` = 8 (F2), `iCommandViewSwitchForward` = 181 (next object) and `iCommandViewSwitchReverse` = 180 (previous). An external-camera project uses ids from the same table, so the numbers look right. Whether DCS accepts them from the hook during a replay is still untested.
- **Work out the viewed unit from the camera.** In F2 the camera points at its unit. `CAM` takes `LoGetCameraPosition()` and `LoGetWorldObjects()` and picks the unit closest to the camera's line of sight. That assumes the camera's `x` vector points forward; `CAM` prints the angle from each axis to the nearest unit so this can be checked.
- **`FOCUS`** combines the two: F2, then next object, one step every 0.15 s, until the camera is on the unit. It gives up after a full cycle or 80 steps, and reports every step.
- **Speed without keystrokes?** The same table gives `iCommandAccelerate` = 53, `iCommandDecelerate` = 191 and `iCommandNoAcceleration` = 246. Round 3 never had these numbers.

**Setup:**
1. Copy the new `hook/spike/ReplayHelperSpike.lua` into `Saved Games\DCS\Scripts\Hooks`.
2. Move `ReplayHelper.lua` out of that folder for this round. Both hooks use the same ports. Don't run the app.
3. Restart DCS. `dcs.log` should contain `REPLAYHELPER (Main): loaded spike-4 (callbacks registered)`.
4. Start `python tools\spike_client.py`, and play `LastMissionTrack.trk`.
5. At once, type `arm 40` so the replay pauses at 0:40. That is before your A-10C is lost at 1:31.

| # | Do | Look for |
|---|----|----------|
| 1 | `globals camera spectat getview setview`, then `globals view` | Any engine function or table that reports or sets the viewed object. The lines are long: just keep them in the log. |
| 2 | Paused at 0:40, press **F2** yourself in DCS, then `cam` | `CAM aimed` should be your A-10C, the unit named on screen. Also note `CAM axes to nearest`: one axis should read close to 0 deg. |
| 3 | Press **F2** again in DCS (next aircraft), then `cam` | `CAM aimed` follows to the aircraft now on screen. |
| 4 | `objects` | Every aircraft with its DCS id. In the Tacview recording your A-10C is `0x5701` and the wingman `A-10C #001` is `0x5001`. Do the ids match? |
| 5 | Press **F1** (cockpit), then `view 8`, then `view 181` twice, then `view 180` | DCS switches to F2 and steps through aircraft by itself. Each `VIEW-AFTER` names the new unit. Note anything that doesn't move. |
| 6 | Press **F1**, then `focus 0x5001` (or `focus A-10C #001` if the ids differ) | `FOCUS-DONE ok`, with the wingman on screen. Then `focus 0x5701` back to your own aircraft. |
| 7 | If `objects` lists a red aircraft: `focus <its id>` | Probably `FOCUS-DONE fail reason=cycled`, which would mean F2 only steps through your own side. Then try `view 26` (iCommandViewAll) or `view 24` (iCommandViewEnemies), and `focus` it again. |
| 8 | `r` to resume at 1x, then `focus 0x5001` while it flies | Does it still land on the wingman while moving? |
| 9 | `p`, then `cmd 53` twice, `cmd 191`, `cmd 246` | `LOCMD-AFTER … accel=` going 2, 3, then down, then 1. If nothing changes, try `cmdx 53` the same way. |
| 10 | `q` | Upload `spike_session.log` and the `REPLAYHELPER` lines from `dcs.log`. Also say what you saw on screen in steps 2–8. |

**If step 5 leaves the camera in the cockpit** (first result: it does), DCS ignores `LoSetCommand` view commands from the hook during a replay. Try the other routes in the same session. Only the client needs restarting for the new commands; the hook is unchanged.

| # | Do | Look for |
|---|----|----------|
| 5a | Press **F1**, then `cmdx 8`, then `digital 8` | Does either switch to F2? `cmdx` runs `LoSetCommand` in the export state; `digital` uses `DCS.dispatchDigitalAction`. |
| 5b | `key f2`, then `key f2` again, then `key ctrl+f2` | The client brings DCS to the front and presses the key, then shows `cam`. Does `CAM aimed` follow what's on screen each time? |
| 6b | Press **F1**, then `kfocus 0x5001` (`objects` gives the id) | `focus` done with keystrokes: it presses F2 until `cam` says the unit is in view. Look for `KFOCUS-DONE ok`, with the wingman on screen. If it ends `reason=cycled`, try `kfocus <id> ctrl+f2`. |

**Afterwards:** delete `ReplayHelperSpike.lua` from `Scripts\Hooks`, and run **Tools → Install / update DCS hook…** in the app to put `ReplayHelper.lua` back.

## Round 3: find the command ids, then get above 1x (done)

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
