import { describe, expect, it } from 'vitest';

import { createGestureDetector, parseControllerMessage } from '../src/controller.js';

describe('parseControllerMessage', () => {
  const detector = createGestureDetector();

  it('accepts plain text and JSON moves', () => {
    expect(parseControllerMessage('JUMP', detector)).toBe('JUMP');
    expect(parseControllerMessage('left\n', detector)).toBe('LEFT');
    expect(parseControllerMessage('"duck"', detector)).toBe('DUCK');
    expect(parseControllerMessage('{"move":"RIGHT"}', detector)).toBe('RIGHT');
    expect(parseControllerMessage('{"movement_type":"JUMP"}', detector)).toBe('JUMP');
    expect(parseControllerMessage(new TextEncoder().encode('JUMP').buffer, detector)).toBe('JUMP');
  });

  it('ignores unknown messages', () => {
    expect(parseControllerMessage('FLY', detector)).toBeNull();
    expect(parseControllerMessage('{"hello":1}', detector)).toBeNull();
    expect(parseControllerMessage('null', detector)).toBeNull();
  });
});

describe('gesture detector', () => {
  const rest = { ax: 0, ay: 1, az: 0 };

  it('classifies spikes on each axis', () => {
    const cases = [
      [{ ax: 0, ay: 3, az: 0 }, 'JUMP'],
      [{ ax: 0, ay: -1, az: 0 }, 'DUCK'],
      [{ ax: 2, ay: 1, az: 0 }, 'RIGHT'],
      [{ ax: -2, ay: 1, az: 0 }, 'LEFT'],
    ];
    for (const [sample, expected] of cases) {
      const detector = createGestureDetector();
      detector.update(rest, 0);
      expect(detector.update(sample, 10)).toBe(expected);
    }
  });

  it('ignores small motion and enforces a cooldown', () => {
    const detector = createGestureDetector({ cooldownMs: 400 });
    detector.update(rest, 0);
    expect(detector.update({ ax: 0.3, ay: 1.2, az: 0 }, 10)).toBeNull();
    expect(detector.update({ ax: 0, ay: 3, az: 0 }, 20)).toBe('JUMP');
    expect(detector.update({ ax: 0, ay: 3, az: 0 }, 100)).toBeNull();
    expect(detector.update({ ax: 0, ay: 4, az: 0 }, 500)).toBe('JUMP');
  });
});
