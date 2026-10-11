import { MOVES, normalizeMove } from './moves.js';

// Turns raw accelerometer samples (in g) into discrete moves. Assumes the sensor is mounted
// with +y pointing up and +x pointing to the player's right; thresholds need tuning on real hardware.
export function createGestureDetector({ threshold = 1.2, cooldownMs = 400, smoothing = 0.9 } = {}) {
  let baseline = null;
  let lastMoveAt = -Infinity;

  return {
    update({ ax, ay, az = 0 }, now = performance.now()) {
      if (baseline === null) {
        baseline = { x: ax, y: ay, z: az };
        return null;
      }
      const dx = ax - baseline.x;
      const dy = ay - baseline.y;
      // Slow-moving baseline removes gravity and sensor tilt drift.
      baseline.x = baseline.x * smoothing + ax * (1 - smoothing);
      baseline.y = baseline.y * smoothing + ay * (1 - smoothing);
      baseline.z = baseline.z * smoothing + az * (1 - smoothing);

      if (now - lastMoveAt < cooldownMs) return null;

      let move = null;
      if (Math.abs(dy) >= Math.abs(dx) && Math.abs(dy) >= threshold) {
        move = dy > 0 ? MOVES.JUMP : MOVES.DUCK;
      } else if (Math.abs(dx) >= threshold) {
        move = dx > 0 ? MOVES.RIGHT : MOVES.LEFT;
      }
      if (move) lastMoveAt = now;
      return move;
    },
  };
}

const textDecoder = new TextDecoder();

// Accepts the message formats the ESP32 firmware may send:
//   "JUMP"                         plain text move
//   {"move": "LEFT"}               JSON move (also "movement_type")
//   {"ax": 0.1, "ay": 2.3, ...}    raw accelerometer sample, classified by the detector
export function parseControllerMessage(raw, detector, now) {
  const text = typeof raw === 'string' ? raw : raw instanceof ArrayBuffer ? textDecoder.decode(raw) : null;
  if (text === null) return null;

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return normalizeMove(text);
  }

  if (typeof data === 'string') return normalizeMove(data);
  if (data && typeof data === 'object') {
    const explicit = normalizeMove(data.move ?? data.movement_type);
    if (explicit) return explicit;
    if (typeof data.ax === 'number' && typeof data.ay === 'number') {
      return detector.update(data, now);
    }
  }
  return null;
}

// The bridge sends {"type": "settings", "jump_buffer_ms": 150} first on every connect, with
// values from tuning.toml. Returns { jumpBufferMs } or null if this is not a settings message.
export function parseSettingsMessage(raw) {
  const text = typeof raw === 'string' ? raw : raw instanceof ArrayBuffer ? textDecoder.decode(raw) : null;
  if (text === null || !text.includes('"settings"')) return null;

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (data?.type !== 'settings') return null;

  const ms = data.jump_buffer_ms;
  return { jumpBufferMs: typeof ms === 'number' && Number.isFinite(ms) && ms >= 0 ? ms : null };
}

export function connectController(url, { onMove, onSettings, onStatus, WebSocketImpl = WebSocket, detector } = {}) {
  const gestures = detector ?? createGestureDetector();
  let socket = null;
  let retryDelay = 1000;
  let retryTimer = null;
  let closed = false;

  function open() {
    onStatus?.('connecting');
    socket = new WebSocketImpl(url);
    socket.binaryType = 'arraybuffer';
    socket.onopen = () => {
      retryDelay = 1000;
      onStatus?.('connected');
    };
    socket.onmessage = (event) => {
      const settings = parseSettingsMessage(event.data);
      if (settings) {
        onSettings?.(settings);
        return;
      }
      const move = parseControllerMessage(event.data, gestures);
      if (move) onMove(move);
    };
    socket.onclose = () => {
      if (closed) return;
      onStatus?.('disconnected');
      retryTimer = setTimeout(open, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 10000);
    };
    socket.onerror = () => socket.close();
  }

  open();

  return {
    close() {
      closed = true;
      clearTimeout(retryTimer);
      socket?.close();
    },
  };
}
