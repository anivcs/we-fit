import { describe, expect, it } from 'vitest';

import { createRng } from '../src/rng.js';
import {
  OBSTACLE,
  OBSTACLE_SPECS,
  generateRow,
  nextRowGap,
  trainBlocksLaneChange,
  trainHasFrontRamp,
  trainSurfaceHeight,
} from '../src/track.js';

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

  it('generates trains at varied lengths that fit both ramps', () => {
    const rng = createRng(817);
    const depths = [];
    for (let i = 0; i < 2000; i++) {
      for (const obstacle of generateRow(rng, 1).obstacles) {
        if (obstacle.type !== OBSTACLE.TRAIN) continue;
        expect(obstacle.spec.depth).toBeGreaterThanOrEqual(10);
        expect(obstacle.spec.depth).toBeLessThanOrEqual(60);
        expect(obstacle.spec.depth).toBeGreaterThan(obstacle.spec.rampLength * 2);
        depths.push(obstacle.spec.depth);
      }
    }
    expect(new Set(depths).size).toBeGreaterThan(1);
  });

  it('randomly omits front ramps only for trains close to a previous train', () => {
    expect(trainHasFrontRamp(() => 0, 12)).toBe(false);
    expect(trainHasFrontRamp(() => 0.4, 12)).toBe(true);
    expect(trainHasFrontRamp(() => 0, 12.01)).toBe(true);
  });

  it('blocks a ground-level lane change into a train beside the player', () => {
    const train = { lane: 0, at: 20, spec: { depth: 30 } };
    expect(trainBlocksLaneChange(25, 1, 0, train, 0.35)).toBe(true);
    expect(trainBlocksLaneChange(19.5, 1, 0, train, 0.35)).toBe(false);
    expect(trainBlocksLaneChange(25, 0, 0, train, 0.35)).toBe(false);
    expect(trainBlocksLaneChange(25, 1, 2, train, 0.35)).toBe(false);
  });

  it('leaves room after a train before the next row', () => {
    const rng = createRng(99);
    for (let i = 0; i < 2000; i++) {
      const trainDepth = 10 + rng() * 50;
      expect(nextRowGap(rng, 1, trainDepth)).toBeGreaterThan(trainDepth + 8);
    }
  });

  it('provides ground ramps and a roof across each train', () => {
    const { depth, height, rampLength } = OBSTACLE_SPECS[OBSTACLE.TRAIN];
    expect(trainSurfaceHeight(-0.1)).toBe(0);
    expect(trainSurfaceHeight(0)).toBe(0);
    expect(trainSurfaceHeight(rampLength / 2)).toBeCloseTo(height / 2);
    expect(trainSurfaceHeight(rampLength)).toBe(height);
    expect(trainSurfaceHeight(depth / 2)).toBe(height);
    expect(trainSurfaceHeight(depth - rampLength / 2)).toBeCloseTo(height / 2);
    expect(trainSurfaceHeight(depth)).toBe(0);
    expect(trainSurfaceHeight(depth + 0.1)).toBe(0);
    const longerTrain = { ...OBSTACLE_SPECS[OBSTACLE.TRAIN], depth: 14 };
    expect(trainSurfaceHeight(7, longerTrain)).toBe(longerTrain.height);
    const noFrontRamp = { ...OBSTACLE_SPECS[OBSTACLE.TRAIN], frontRamp: false };
    expect(trainSurfaceHeight(noFrontRamp.rampLength / 2, noFrontRamp)).toBe(0);
    expect(trainSurfaceHeight(noFrontRamp.rampLength, noFrontRamp)).toBe(noFrontRamp.height);
  });
});
