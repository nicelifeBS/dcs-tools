# Milestone 0 spike: what can a hook do during a replay?

The spike has two parts: a throwaway DCS hook and a console client. Running them once tells us how the real hook has to work:

1. Can the hook pause, resume and read the clock during a `.trk` replay?
2. Can it change time acceleration itself (`LoSetCommand`), or does the app have to press `Ctrl+Z` / `Alt+Z` / `Shift+Z` in the DCS window?
3. Where is the mission start time, and does DCS model time line up with Tacview time?
4. How precisely does a hook-side stop land at 4x?

Rounds 1–3 answered those, rounds 4–6 the F2 view question (can the hook put DCS's F2 view on a given unit, and tell which unit the camera is on?). Rounds 7–8 ask whether the app can set the free camera's speed to match an aircraft, helicopter or missile; that round is still partly open.

Finished rounds, with their full results and test steps, are in [SPIKE_DONE.md](SPIKE_DONE.md).

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
- **Free camera speed** (rounds 7–8): object speeds are readable (`movers`), and the camera flies in replay time, so its set speed compares directly with an object's speed at any replay speed, paused or in slow motion. The speed is not kept across a track reload.
  - No numeric command ids exist, so the app has to send keystrokes (`LAlt+Num*` / `LAlt+Num/`) or wheel notches.
  - Keys step the speed by x1.1 per press (from 5.0 m/s at standstill) and never cross zero. The wheel steps the signed speed by 1.13 m/s per notch (down = forward, up = backward) and crosses zero, so backward matching works.
  - The speed ramps (about 25 m/s per second): wait about 3 s after each step before reading `camv`.
  - A multi-notch wheel event counts as one or two notches, so the app sends one event per notch, 0.02 s apart (0.03 s apart all 100 were counted).
  - **Plan for the app:** coarse steps with the keys (forward only), then fine steps with the wheel until `camv model=` is within about 1 m/s of `along=`. Held at 164, 140 and 112 m/s (+-1 m/s); a followed A-10C drifted from 34 m to 263 m, so the wheel step is needed.
- **F2 view and focus** (rounds 4–6): see the F2 bullet above.

## Still open (round 8)

**Setup:** copy `hook/spike/ReplayHelperSpike.lua` to `Saved Games\DCS\Scripts\Hooks`, move `ReplayHelper.lua` out of that folder, don't run the app, restart DCS. In a terminal run `python tools\spike_client.py` and play a track. Afterwards delete the spike hook and reinstall the real one (**Tools → Install / update DCS hook…**).

**DCS** = what you do in the game, **Tool** = what you type at the `>` prompt of `spike_client.py`.

| # | DCS | Tool | Look for |
|---|-----|------|----------|
| 6b | Same, but turn the camera to look **at the aircraft's nose** (it flies toward you), then `movers 300` | the `along=` and `dir=` of that aircraft | `along` is negative and `dir=back`: the camera has to fly backward (`Num/`) to keep pace. Also try looking sideways: `side=` is the part the camera cannot follow |
| 7 | Replay running at 1x, then 2x (`key up`) | `camv` | does the camera keep its distance to the aircraft at both speeds? |
| 8 | A track with missiles or helicopters, replay running | `track on`, then `movers` while one is in the air | `kind=weapon` or `kind=heli`, their speed and `from=`; `weapon_types=` in the first line |
| 9 | | `q` | send `spike_session.log` |

**What it decides:** whether the app can keep the camera at an object's distance at 1x and 2x, and how the app handles direction (steps 6b, 7), and helicopters and missiles (step 8, postponed).

## Send back

- `spike_session.log`
- The `REPLAYHELPER` lines from `dcs.log`, for example from:
  `findstr REPLAYHELPER "%USERPROFILE%\Saved Games\DCS\Logs\dcs.log" > replayhelper.txt`
- Short notes on tests 4–9: which speed method worked, the speed steps you saw, whether speed survives a pause, and whether the stop landed on the right moment.

Delete `ReplayHelperSpike.lua` from `Scripts\Hooks` afterwards. The real hook replaces it.
