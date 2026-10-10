import { MOVES } from './moves.js';

const KEY_MOVES = {
  ArrowLeft: MOVES.LEFT,
  KeyA: MOVES.LEFT,
  ArrowRight: MOVES.RIGHT,
  KeyD: MOVES.RIGHT,
  ArrowUp: MOVES.JUMP,
  KeyW: MOVES.JUMP,
  Space: MOVES.JUMP,
  ArrowDown: MOVES.DUCK,
  KeyS: MOVES.DUCK,
};

const PAUSE_KEYS = new Set(['Escape', 'KeyP']);
const SWIPE_MIN_PX = 30;

function isTyping(target) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

export function attachKeyboard({ onMove, onPause }) {
  window.addEventListener('keydown', (event) => {
    if (event.repeat || isTyping(event.target)) return;
    if (PAUSE_KEYS.has(event.code)) {
      onPause();
      return;
    }
    const move = KEY_MOVES[event.code];
    if (move) {
      event.preventDefault();
      onMove(move);
    }
  });
}

export function attachSwipe(element, { onMove }) {
  let start = null;
  element.addEventListener('touchstart', (event) => {
    const touch = event.changedTouches[0];
    start = { x: touch.clientX, y: touch.clientY };
  }, { passive: true });
  element.addEventListener('touchend', (event) => {
    if (!start) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    start = null;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_MIN_PX) return;
    if (Math.abs(dx) > Math.abs(dy)) onMove(dx > 0 ? MOVES.RIGHT : MOVES.LEFT);
    else onMove(dy < 0 ? MOVES.JUMP : MOVES.DUCK);
  }, { passive: true });
}
