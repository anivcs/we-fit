import { describe, expect, it } from 'vitest';

import { BUFFER_SECONDS, createInputBuffer } from '../src/inputBuffer.js';

describe('input buffer', () => {
  it('returns a held move while it is fresh, then empties', () => {
    const buffer = createInputBuffer(0.15);
    buffer.hold('JUMP', 1.0);
    expect(buffer.pending).toBe('JUMP');
    expect(buffer.take(1.1)).toBe('JUMP');
    expect(buffer.pending).toBeNull();
    expect(buffer.take(1.1)).toBeNull();
  });

  it('drops a move once its window has passed', () => {
    const buffer = createInputBuffer(0.15);
    buffer.hold('JUMP', 1.0);
    expect(buffer.take(1.2)).toBeNull();
    expect(buffer.pending).toBeNull();
  });

  it('accepts a move exactly at the end of the window', () => {
    const buffer = createInputBuffer(0.15);
    buffer.hold('JUMP', 1.0);
    expect(buffer.take(1.15)).toBe('JUMP');
  });

  it('keeps only the latest move', () => {
    const buffer = createInputBuffer(0.15);
    buffer.hold('JUMP', 1.0);
    buffer.hold('DUCK', 1.05);
    expect(buffer.take(1.1)).toBe('DUCK');
  });

  it('can be cleared', () => {
    const buffer = createInputBuffer();
    buffer.hold('JUMP', 0);
    buffer.clear();
    expect(buffer.take(0.01)).toBeNull();
  });

  it('has a window short enough that an early double press cannot survive a jump', () => {
    // A full jump in game.js is about 0.63 s in the air (2 * 12 / 38)
    expect(BUFFER_SECONDS).toBeGreaterThan(0.05);
    expect(BUFFER_SECONDS).toBeLessThan(0.3);
  });

  it('uses a window set later, and 0 turns it off', () => {
    const buffer = createInputBuffer();
    buffer.setWindow(0.3);
    buffer.hold('JUMP', 10);
    expect(buffer.take(10.3)).toBe('JUMP');
    buffer.setWindow(0);
    buffer.hold('JUMP', 10);
    expect(buffer.take(10.001)).toBeNull();
  });
});
