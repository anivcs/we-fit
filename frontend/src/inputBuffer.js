// Remembers one move that arrived a moment too early, so it can run as soon as it becomes legal.
//
// A JUMP pressed just before landing is a real intent, not a mistake. Without a buffer it is
// dropped and the player has to press again, which feels like the controller missed it.
//
// Times are in game seconds (they stop while the game is paused). A move is only kept for
// `windowSeconds`, so an early double-fire from a noisy controller expires long before the
// player lands instead of causing a surprise second jump.

export const BUFFER_SECONDS = 0.15;

export function createInputBuffer(initialWindowSeconds = BUFFER_SECONDS) {
  let windowSeconds = initialWindowSeconds;
  let held = null;

  return {
    // Applies to moves held from now on; 0 turns the buffer off.
    setWindow(seconds) {
      windowSeconds = Math.max(0, seconds);
    },

    get window() {
      return windowSeconds;
    },

    // Keeps only the latest move; a newer one replaces an older one.
    hold(move, now) {
      held = { move, expiresAt: now + windowSeconds };
    },

    clear() {
      held = null;
    },

    // Returns the held move if it is still fresh, and always empties the buffer.
    take(now) {
      if (held === null) return null;
      const { move, expiresAt } = held;
      held = null;
      return now <= expiresAt ? move : null;
    },

    get pending() {
      return held?.move ?? null;
    },
  };
}
