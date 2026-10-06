# Milestone 0 spike: what can a hook do during a replay?

The spike has two parts: a throwaway DCS hook and a console client. Running them once tells us how the real hook has to work:

1. Can the hook pause, resume and read the clock during a `.trk` replay?
2. Can it change time acceleration itself (`LoSetCommand`), or does the app have to press `Ctrl+Z` / `Alt+Z` / `Shift+Z` in the DCS window?
3. Where is the mission start time, and does DCS model time line up with Tacview time?
4. How precisely does a hook-side stop land at 4x?

Rounds 1–3 answered those, rounds 4–6 the F2 view question (can the hook put DCS's F2 view on a given unit, and tell which unit the camera is on?). Round 7 asks whether the app can set the free camera's speed to match an aircraft, helicopter or missile.

Nothing is written to the DCS install folder. The hook only logs and answers on localhost UDP ports 47810 and 47811.

## Setup

1. Copy `hook/spike/ReplayHelperSpike.lua` to `%USERPROFILE%\Saved Games\DCS\Scripts\Hooks\`. Create the `Hooks` folder if it doesn't exist, and use `DCS.openbeta` instead of `DCS` if that's your Saved Games folder.
2. Start DCS. `Saved Games\DCS\Logs\dcs.log` should contain:
   `REPLAYHELPER (Main): loaded spike-7 (callbacks registered)`
3. In a terminal, from the `dcs-replay-helper` folder, run `python tools\spike_client.py`. It needs Python 3.10 or newer and no packages. It writes everything to `spike_session.log` in the current folder.
4. In DCS, play the sample track `LastMissionTrack.trk`. Within a second the client should print `HELLO spike-7`. Typing `s` then shows the live `STATE` line.

## Results (spike finished)

- **Speed control is `DCS.dispatchDigitalAction`** (rounds 4–5, hook 0.2.0): `iCommandAccelerate` 53, `iCommandDecelerate` 191 and `iCommandNoAcceleration` 246 take the same steps as the keys, with no window focus. The ids come from a community-extracted table; `LoSetCommand` ignores them.
- **Before that, speed control was keystrokes** (rounds 1–3, still used with hook 0.1.0). `LCtrl+Z`, `LAlt+Z` and `LShift+Z` are sent as scan codes to the focused DCS window. They work during playback, including while paused.
  - Above 1x, each `LCtrl+Z` adds 1x: 1 → 2 → 3 → 4. Below 1x, `LAlt+Z` halves the speed (0.5, 0.25). `LShift+Z` returns to 1x.
  - `Export.LoGetModelTimeAcceleration()` (`accel=`) reports the new speed immediately, even while paused.
- **F2 on a given aircraft** (rounds 4–6): `dispatchDigitalAction(8)` acts as the F2 key, so the hook steps F2 until the camera, from `LoGetCameraPosition`, is on the aircraft. DCS id = Tacview id + 0xFFFFFF.
- **Pause and resume** from the hook work. The speed is kept through a pause.
- **The hook's frame-checked stop** landed within 0.002 s at 1x and 0.015 s at 4x.
- **Model time is seconds since mission start.** The mission start time is in `DCS.getCurrentMission().mission.start_time`.

## Round 7: match the free camera's speed to an object (open)

**Goal:** list the aircraft, helicopters and missiles near the camera with their speeds, pick one, and have the free camera (F11) fly at that speed, while the replay is paused.

**What is known, and what the round has to find out:**

| Question | Status |
|----------|--------|
| Can the hook read an object's speed? | **Not directly.** `LoGetWorldObjects` gives position and heading, no velocity. The spike measures it: the change of position over model time between two samples, kept per object. |
| ...while paused? | Positions don't change while paused, so the spike keeps the last velocity measured while the sim ran (`age=` says how old). The seek's own stop is the usual case: the replay runs at up to 4x into the pause, so the velocities are fresh. The Tacview recording the app already reads would give the exact speed at the paused moment, with no history needed, and is the fallback if this isn't enough. |
| Are missiles listed? | **Unknown.** `LoGetWorldObjects()` lists units; weapons in flight are believed to be under `LoGetWorldObjects('ballistic')`. `TRACK` asks for both and `MOVERS` prints the `type=level1/level2/level3/level4` of every weapon and a count per type, so missiles can be told from bombs, rockets and shells. |
| Group and pilot names? | Aircraft and helicopters: `UnitName` and `GroupName`. In a replay the unit name is the pilot name (round 6: they equal Tacview's `Pilot` and `Group`), and `human=true` marks a player. A weapon has a name (`AIM-120C`) but no unit or group, so the spike says who probably fired it: the aircraft of the weapon's side nearest to where it first appears, within 2 km, as the app's Tacview events do. |
| What changes the free camera's speed? | **Unknown, the main question.** The free camera (F11) has forward and backward movement bindings (confirmed: LAlt+`/` and LAlt+`*`, presumably on the numpad. A community key list has `*` forward and `/` backward; which is which is for steps 4–5 to show, from the sign of `fwd=`) and speed and acceleration settings in the view config (`View.lua`). I couldn't confirm either from DCS itself: no DCS install here, and the forum pages were unreachable. `FINDCAM` lists the binding lines from your `Config` folder, with the command names. |
| Can a hook send it? | **Probably**, as for time acceleration and F2: `DCS.dispatchDigitalAction(<id>)` reaches input commands in a replay (rounds 4–6). It needs the numeric id of the command; the keystrokes work without it (Windows). |
| Can the hook read the camera's speed? | **Yes in principle:** `LoGetCameraPosition().p` moves with the free camera, so the speed is its change over **real** time. `CAMV` and `camv=` in STATE give it, total and along the camera's forward axis (`camfwd=`, signed: negative is backwards). Whether the free camera moves, and the position updates, while the sim is paused is untested. |

If the speed commands are steps (like time acceleration), the app can steer the way `dcs/speed.py` does: press, read `camfwd=`, press again until it is as close to the object's speed as the steps allow. If there is an axis or a setting to write, it can set the value directly.

**Setup:** as in round 4: copy the new `hook/spike/ReplayHelperSpike.lua` into `Saved Games\DCS\Scripts\Hooks`, move `ReplayHelper.lua` out of that folder (both hooks use the same ports) and don't run the app. Afterwards delete the spike hook and reinstall the real one from the app (**Tools → Install / update DCS hook…**). Run `python tools\spike_client.py`, play a track that has missiles in flight if you can (the F-4E vs MiG-29s one), and pause. Numpad keys and F11 are sent to the DCS window like the F-keys before: `key f11`, `key alt+num*`, ...

| # | Do | Look for |
|---|----|----------|
| 1 | `findcam` | `CAMCMD <file>:<line> <binding>` lines. Note the command names (`iCommand...`) and keys for the free camera's movement and speed. Everything about the camera's speed or "Camera forward/backward" counts. `findcam Scripts` searches the scripts too |
| 2 | `globals <part of a name from 1, lower case>`, e.g. `globals viewcam` | `GLOBALS ... iCommand...=<n>`: the id. If none show up (round 3's experience), carry on with keys |
| 3 | Pause (`p`). Press F11 in DCS (try LCtrl+F11 too if the camera doesn't leave the aircraft), then `camv` | `CAMV speed=0.00 ... via=Export` with the camera standing still. If `CAMV unknown`, the camera isn't readable in this view: say which view you were in |
| 4 | `kcam alt+num* 5 1.0` (if the keys aren't on your numpad, tell me and I'll add the main-row `/` and `*`) | One `CAMV` line after each press. Does the speed step (and by how much), and does it show up while paused (`paused=true`, speed above 0)? |
| 5 | Stop the camera by hand (the stop key, or the key from 1), then `kcam alt+num/ 5 1.0` | The opposite sign of `fwd=` to step 4. Note which key is forward, and compare the step sizes. Does pressing the opposite key slow the camera down first, or reverse it at once? |
| 6 | If 1–2 gave an id: `digital <id>`, wait a second, `camv` | `LOCMD-AFTER digital id=... camv=... camfwd=...` changes with no keystroke and no window focus |
| 7 | `track on`, `r` for 10 s, `p`, `movers` | `MOVERS listed=... plane=... heli=... weapon=... weapon_types=...` then one `MOV` line per object: `kind`, `unit`, `group`, `speed=... m/s ... kt ... km/h`, `dist=` (nearest to the camera first), `age=`. Weapons also `from=`. Compare an aircraft's speed with its cockpit or Tacview speed |
| 8 | Fire or replay a missile, `movers` while it flies and again after `p` | A `kind=weapon` line with a name like `AIM-120C` and `from=<unit>/<group>`. Check `weapon_types=`: which `level2` is the missile? If `weapon=0` with a missile in the air, say so |
| 9 | `movers 5000` | Only the objects within 5 km of the camera |
| 10 | `q` | Upload `spike_session.log` and the `REPLAYHELPER` lines from `dcs.log`. Say what the camera did on screen in 3–6 |

**What the results decide:**
- **Speeds:** if the measured speeds look right, the app gets an object list (aircraft, helicopters, missiles; kind, name, group, pilot, speed in kt, km/h and m/s, distance) fed by the hook, and a *Match camera speed* button.
- **Camera:** steps, an axis or a setting decides how the controller works and how close it can get; no working route (no id, keys only on Windows) means keystrokes, with the focus problems that brings.
- **Missiles:** if `ballistic` lists nothing, the missile speeds come from the Tacview recording instead.

## Round 6: focus by stepping F2 (done)

**Results:** focusing works, with no keystrokes and no window focus.
- **Every `focus` landed:** from the cockpit to the wingman in 2 steps (0.31 s), and on to C-17 #004 in 4 steps (0.63 s). Paused and in flight alike.
- **`fast` (a step every 0.05 s) doesn't overshoot:** 2 steps in 0.11 s. The camera has moved by the next check.
- **F2 reaches the other side.** In the new track (`tests/data/Tacview-20261004-131442-DCS-CWG.trk`, F-4E vs MiG-29s on GermanyCW), `focus 0x1003800` stepped from the player's F-4E through the MiG-29s to the target in 5 steps.
- **The F2 order is all aircraft by DCS id**, both coalitions, wrapping from the highest id to the lowest: the F-4E (`0x1006f00`) went next to the first MiG (`0x1003500`).
- **The id mapping holds:** for all 7 aircraft in the new recording, DCS id = Tacview id + 0xFFFFFF, and unit and group names equal Tacview's `Pilot` and `Group`.
- **A fast jet can sit outside 5° for a moment** just after F2 switches to it: one MiG-29 showed 7.0° at 35.6 m. That one wasn't the target, but the app should allow more (15°, with the cockpit check still ruling out the camera sitting inside an aircraft), so it doesn't step past the target.

**What round 6 tested, and its steps:**

Round 5 showed that command 8 (`iCommandViewAir`), sent by `digital` or `export`, does what pressing F2 does: from the cockpit it gives F2 on your own aircraft, and in F2 it steps to the next aircraft. Next/previous object (181/180) do nothing. `spike-6` has `focus` step with 8, and counts a unit as viewed within 5° (the camera trails by up to 1.6° in flight).

**Setup:** as before, with `spike-6`. `arm 40` at once.

| # | Do | Look for |
|---|----|----------|
| 1 | Press **F1**, then `focus 0x1005000` | `FOCUS-DONE ok … steps=2`: F2 on your aircraft, then the wingman, who is on screen. |
| 2 | `focus 0x1005400` | Steps on through the C-17s to C-17 #004: `FOCUS-DONE ok … steps=4`. |
| 3 | Press **F1**, then `focus 0x1005000 fast` | Still `ok`, with no overshoot past the wingman, at a step every 0.05 s. If it overshoots, the camera needs longer than that to move. |
| 4 | `r`, then `focus 0x1005100` while it flies, then `p` | `ok` on C-17 #001 while moving. |
| 5 | Optional, with a track that has red aircraft: `objects`, then `focus <red id>` | Does stepping F2 reach the other side, or end `reason=cycled`? |
| 6 | `q` | Upload `spike_session.log`. |

## Round 5: focus without keystrokes (done)

**Results:**
- **Command 8 steps F2.** `view 8` from the cockpit gave F2 on the player's aircraft; `view 8` in F2 stepped to the next aircraft (wingman, C-17 #001, C-17 #002), as the F2 key does.
- **Next/previous object (181/180) do nothing**, by the `digital` and the `export` route alike. `focus` stepped with 181, so it never moved.
- **Speed works through `digital`:** `digital 53` took 1x to 2x, `digital 191` 2x back to 1x and then 0.5, 0.25 and 0.125, and `digital 246` back to 1x. The same steps as the keys, with no window focus. LoSetCommand still does nothing for speed.
- **In flight, F2 trails its aircraft by up to 1.6°** (0.0 when paused).
- **In the cockpit, `cam` now says `aimed none`.**

**What round 5 tested, and its steps:**

Round 4 showed that the hook can switch to F2 through `DCS.dispatchDigitalAction` or through `LoSetCommand` in the export state, but not through `LoSetCommand` in its own state. `spike-5` sends view commands by those routes (`digital` by default, or `export`), and `FOCUS` now uses them. It also counts a unit as viewed only when it is within 3° of straight ahead and the camera is not inside another unit. Round 4's first `kfocus` stopped on the wingman while the camera was still in the cockpit.

**Setup:** as in round 4, with `spike-5`.

| # | Do | Look for |
|---|----|----------|
| 1 | Press **F1**, then `cam` | `CAM aimed none`: the cockpit no longer counts as viewing the wingman. |
| 2 | `view 8`, then `view 181` twice, then `view 180` | F2 on your A-10C, then the next aircraft, the next, and back. Each `VIEW-AFTER digital … aimed` matches the screen. |
| 3 | Press **F1**, then `view export 8`, `view export 181` | The same through the export state. |
| 4 | Press **F1**, then `focus 0x1005000` | `FOCUS-DONE ok` with the wingman on screen, with no keystrokes and no window focus. Then `focus fubar` back to your own aircraft, and `focus 0x1005400 prev` (the last C-17, one step backwards). |
| 5 | `focus A-10C #001 export` | The same through the export state. |
| 6 | `r`, then `focus 0x1005000` while it flies, then `p` | Does it land on the wingman while moving? |
| 7 | Paused: `digital 53` twice, `digital 191`, `digital 246` | `LOCMD-AFTER digital … accel=` changing. If so, the app could set the speed without keystrokes too. |
| 8 | Optional, with a track that has red aircraft: `objects`, then `focus <red id>` | Does F2 reach the other side? If it ends `reason=cycled`, try `view 26` or `view 24` and `focus` again, then `kfocus <id> ctrl+f2`. |
| 9 | `q` | Upload `spike_session.log`. |

**Afterwards:** delete `ReplayHelperSpike.lua` and reinstall `ReplayHelper.lua` from the app, as in round 4.

## Round 4: put the F2 view on a unit (done)

**Results:**
- **The viewed unit can be worked out.** With F2 pressed by hand, `cam` named the aircraft on screen every time. The camera sits 43.3 m from an A-10C and 134.7 m from a C-17, 0.0–0.1° off its forward axis. The camera's `x` vector is forward. In the cockpit, the camera is 4.7 m from the player's aircraft, 145° off.
- **The ids differ from Tacview, by a fixed amount.** DCS id = Tacview id + 0xFFFFFF: the player's A-10C is `0x5701` in Tacview and `0x1005700` in DCS, the wingman `0x5001` and `0x1005000`. Unit and group names match Tacview's `Pilot` and `Group`.
- **`LoSetCommand` from the hooks state doesn't touch the view** during a replay (`ok=true`, camera unchanged). `cmdx 8` (export state) and `digital 8` (`DCS.dispatchDigitalAction`) both switched to F2.
- **F2 steps through the player's coalition** in id order, including C-17s 250 km away. Ctrl+F2 steps backwards. The sample has no red aircraft, so whether F2 reaches the other side is open.
- **`kfocus` works:** 5 presses of F2, 2.0 s, to reach the player's aircraft from the wingman.
- **The time-acceleration ids do nothing** through `LoSetCommand`, from the hooks state or the export state: `accel=` stays 1.000 after 53, 191 and 246. `digital 53` wasn't tried.
- **Other camera functions exist:** `Export.LoSetCameraPosition`, `LoForceCamera`, `LoCreateCameraRequest`, `LoSendForceCamera` and `DCS.setCameraToAirdrome`. Not needed if F2 stepping works.

**What round 4 tested, and its steps:**

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
