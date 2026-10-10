import { describe, expect, it } from 'vitest';

import { createRng } from '../src/rng.js';
import { OBSTACLE, OBSTACLE_SPECS, generateRow, nextRowGap } from '../src/track.js';

describe('rng', () => {
  it('is deterministic for a seed', () => {
    const a = createRng(42);
    const b = createRng(42);
    const c = createRng(43);
    const seqA = Array.from({ length: 5 }, a);
    expect(Array.from({ length: 5 }, b)).toEqual(seqA);
    expect(Array.from({ length: 5 }, c)).not.toEqual(seqA);
    expect(seqA.every((v) => v >= 0 && v < 1)).toBe(true);
  });
});

describe('track generation', () => {
  it('produces the same layout for the same seed', () => {
    const layout = (seed) => {
      const rng = createRng(seed);
      return Array.from({ length: 50 }, () => generateRow(rng, 0.5));
    };
    expect(layout(7)).toEqual(layout(7));
  });

  it('always leaves a way through every row', () => {
    for (const difficulty of [0, 0.5, 1]) {
      const rng = createRng(1234);
      for (let i = 0; i < 2000; i++) {
        const { obstacles, coins } = generateRow(rng, difficulty);
        const lanes = obstacles.map((o) => o.lane);
        expect(new Set(lanes).size).toBe(lanes.length);
        expect(lanes.length).toBeLessThan(3);
        expect(obstacles.filter((o) => o.type === OBSTACLE.TRAIN).length).toBeLessThanOrEqual(1);
        for (const coin of coins.filter((c) => c.height < 2)) {
          expect(lanes).not.toContain(coin.lane);
        }
      }
    }
  });

  it('leaves room after a train before the next row', () => {
    const rng = createRng(99);
    for (let i = 0; i < 2000; i++) {
      expect(nextRowGap(rng, 1)).toBeGreaterThan(OBSTACLE_SPECS[OBSTACLE.TRAIN].depth + 8);
    }
  });
});
