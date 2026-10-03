# DCS Replay Helper

A desktop helper that drives a DCS track replay that is already running.

- Play and pause the replay.
- Jump forward to a moment you picked beforehand in Tacview: a bookmark or event from the `.acmi` file. The jump uses a speed cap, for example at most 4x.
- Stop with a pre-roll before the event, plus an optional post-roll stop after it.

The app talks over localhost UDP to a small hook script in `Saved Games\DCS\Scripts\Hooks`. The hook watches the clock every frame, so it can pause exactly on the target time.

## Status

**Milestone 0: spike.** There's no app yet. `hook/spike/ReplayHelperSpike.lua` and `tools/spike_client.py` probe what a hook can do during a replay. See [SPIKE.md](SPIKE.md) for how to run them.

## Layout

```
hook/spike/ReplayHelperSpike.lua   # throwaway probe hook (milestone 0, spike-2)
tools/spike_client.py              # console client for the spike (stdlib only)
tests/test_spike_hook.py           # runs the hook in Lua 5.1 (lupa) against a mocked DCS
```

## Development

```
cd dcs-replay-helper
uv run pytest
```
