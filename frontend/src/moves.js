// Must match the backend's MovementType enum.
export const MOVES = Object.freeze({
  JUMP: 'JUMP',
  DUCK: 'DUCK',
  LEFT: 'LEFT',
  RIGHT: 'RIGHT',
});

export function normalizeMove(value) {
  if (typeof value !== 'string') return null;
  const upper = value.trim().toUpperCase();
  return MOVES[upper] ?? null;
}
