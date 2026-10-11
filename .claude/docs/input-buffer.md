# Input buffer for rapid repeats (branch `buffer`)

## Problem

Rapid repeated inputs in one direction (for example a run of downs) were dropped until the
sequence stopped.

Cause: after a gesture fires, its axis must be still for `rest_ms` before that direction can
fire again (`GestureDetector._rested`). During a rapid series the axis never settles, so every
later gesture failed the rest gate. The cooldown was not the culprit: it is measured from the
last *fired* gesture, so it always expires.

## Changes

| File | Change |
| --- | --- |
| `bridge/src/wefit_bridge/gestures.py` | `DirectionConfig` gains `queue_size` (default 0) and `queue_s` (default 0.4). `GestureDetector` gains edge detection, a repeat rule, a per-direction queue and `_release`. |
| `bridge/src/wefit_bridge/tuning.py` | Reads `queue` and `queue_ms` from each direction row. `queue` is cast to an int. |
| `tuning.toml` | Documents both settings. Every `[usb]` and `[ble]` row gets `queue = 2, queue_ms = 400`. |
| `README.md` | Tuning table: two new rows, example rows updated. |
| `bridge/tests/test_gestures.py` | Six new tests (queued repeats, bound, staleness, off = old behaviour, rebound is not a repeat, other direction not lost). |

### Behaviour

1. **Edge detection.** A detection is "new" only if the previous sample did not detect the same
   direction. One physical spike spans several 50 Hz samples; without this the tail of a spike
   would be queued as extra repeats.
2. **Repeat rule (needs `queue > 0`).** A new spike in the direction last fired on that axis
   skips the rest gate. A rebound points the other way, so it cannot be mistaken for a repeat.
3. **Queue.** A repeat blocked only by the cooldown is queued (up to `queue` items). It fires
   when the cooldown ends and is discarded after `queue_ms`.
4. **One gesture per sample.** If a queued repeat fires, a fresh spike in the same sample is
   queued for the next sample (at most one sample, 20 ms, of delay).
5. `queue = 0` restores the old behaviour exactly. `reset()` clears the queue.

## Review

**Necessary?**
- Edge detection and the repeat rule that skips the rest gate: yes. They fix the reported bug.
  Without them the queue alone would not help, because queued items were never released while the
  axis kept moving.
- The queue: not needed to fix the hang. It was requested, and it adds repeats that would
  otherwise be lost to the cooldown. It is off by default in code and tunable per direction.
- The one-sample deferral in point 4 is a side effect of the one-gesture-per-sample rule, not a
  goal. It was added after review so a mixed config (queue on for one direction, off for
  another) does not drop the other direction.

**Does it generalise to different-direction combos (down + left)?** Nothing needed changing there.
- Left/right and up/down are on different axes. Each axis has its own rest gate, and cooldown is
  per direction, so down then left already fired immediately and still does. The queue never
  engages, because nothing blocks the second gesture.
- Opposite directions on the same axis (up then down) are deliberately **not** buffered. The
  rest gate exists to reject the rebound spike after a motion, and a rebound looks exactly like
  a real opposite gesture. Buffering it would replay phantom moves.
- So the feature is constrained to same-direction repeats, which is the only case where the
  gate cannot tell intent from noise by direction alone.

**Industry convention.** Input buffering in games (fighting games, platformers, the original
Subway Surfers) holds a short window of recent intent, usually one to a few frames up to about
200 ms, and replays it when the action becomes legal. It applies to any action type, but it
sits in the game, where "legal" is known. The bridge version is narrower: a time-based
debounce on one physical sensor, limited to repeats. That scope is appropriate for a
signal-level filter. Two things differ from convention and are worth knowing:
- The default window (400 ms) is longer than a typical game buffer. Reduce it if moves feel
  late.
- Convention is often "keep only the latest buffered input"; this is a FIFO of up to
  `queue` entries.

## Follow-up: does the bridge need feedback from the game?

Short answer: **the bridge can filter blindly for physical debouncing, which is what this
change does. Game-state-aware buffering belongs in the game.**

- What the bridge knows: acceleration and time. That is enough to decide whether a spike is a
  new deliberate gesture, a rebound or the tail of the same spike.
- What it cannot know: whether the move is currently legal (mid-jump, mid-lane-change, at the
  edge lane, paused, dead). Conventional input buffering is keyed to that state, so a buffer that
  waits for "can act again" has to live in the game. The bridge queue waits only for a fixed
  cooldown.
- Consequence of blind filtering: a queued repeat may be delivered when the game would have
  rejected it. That is harmless for one-shot moves the game already ignores when illegal, and
  bounded by `queue_ms` (400 ms) and `queue` (2). Nothing is lost that the game could have used.
- Gap: the WebSocket sink ignores everything the game sends, so a browser game cannot call
  `reset()` at a round start. `Controller.reset()` (Python) clears the queue; the browser path
  relies on the 400 ms expiry. If this matters, add a `{"reset": true}` message from the game
  and have the sink call `pipeline.reset()`. That is the only feedback worth adding, and it is
  not required for correctness today.
- Recommendation: keep the bridge as a stateless-to-the-game debouncer, keep `queue` small, and
  if gameplay needs longer or state-aware buffering, do it in the frontend on the received
  `move` messages.

## Verification

`pytest bridge/tests -m "not usb and not bluetooth"`: 120 passed. Not run against a real board,
so `queue = 2, queue_ms = 400` is an untuned starting point.
