import { describe, expect, it } from 'vitest';

import { createRng } from '../src/rng.js';
import {
  FIRST_MOVING_TRAIN_SCORE,
  OBSTACLE,
  OBSTACLE_SPECS,
  canLandOnTrain,
  generateRow,
  generateMovingTrainPhase,
  isOnTrainRoof,
  movingTrainPhaseBlocksObstacle,
  nextMovingTrainPhaseStart,
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

  it('generates trains at varied lengths that fit the front ramp', () => {
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

  it('randomly omits front ramps for trains regardless of spacing', () => {
    expect(trainHasFrontRamp(() => 0)).toBe(false);
    expect(trainHasFrontRamp(() => 0.4)).toBe(true);
    expect(trainHasFrontRamp(() => 0.99)).toBe(true);

    const rng = createRng(52);
    const total = 1000;
    let rampless = 0;
    for (let i = 0; i < total; i++) {
      if (!trainHasFrontRamp(rng)) rampless++;
    }
    const ramplessRatio = rampless / total;
    expect(ramplessRatio).toBeGreaterThan(0.35);
    expect(ramplessRatio).toBeLessThan(0.45);
  });

  it('blocks a ground-level lane change into a train beside the player', () => {
    const train = { lane: 0, at: 20, spec: { depth: 30 } };
    expect(trainBlocksLaneChange(25, 1, 0, train, 0.35)).toBe(true);
    expect(trainBlocksLaneChange(19.5, 1, 0, train, 0.35)).toBe(false);
    expect(trainBlocksLaneChange(25, 0, 0, train, 0.35)).toBe(false);
    expect(trainBlocksLaneChange(25, 1, 2, train, 0.35)).toBe(false);
  });

  it('recognizes train-roof lane changes without treating them as ground impacts', () => {
    expect(isOnTrainRoof(3.2, 3.2, true)).toBe(true);
    expect(isOnTrainRoof(3.2, 3.2, false)).toBe(false);
    expect(isOnTrainRoof(0, 3.2, true)).toBe(false);
  });

  it('generates moving-train phases with randomized duration and safe convoy lanes', () => {
    const rng = createRng(734);
    let threeTrainPhases = 0;
    for (let i = 0; i < 1000; i++) {
      const phase = generateMovingTrainPhase(rng, 3000);
      expect(phase.start).toBe(3000);
      expect(phase.end - phase.start).toBeGreaterThanOrEqual(200);
      expect(phase.end - phase.start).toBeLessThan(300);
      expect(phase.lanes.length).toBeGreaterThanOrEqual(1);
      expect(phase.lanes.length).toBeLessThanOrEqual(3);
      expect(new Set(phase.lanes).size).toBe(phase.lanes.length);
      if (phase.lanes.length === 3) threeTrainPhases++;
      expect(phase.convoys.length).toBeGreaterThan(0);
      for (const convoy of phase.convoys) {
        expect(convoy.trains.length).toBe(phase.lanes.length);
        expect(convoy.trains.map(({ lane }) => lane)).toEqual(phase.lanes);
        for (const { speed, offset, frontRamp } of convoy.trains) {
          expect(frontRamp).toBe(false);
          expect(speed).toBeGreaterThanOrEqual(8);
          expect(speed).toBeLessThan(42);
          expect(offset).toBeGreaterThanOrEqual(0);
        }
      }
      const protectedLane = phase.lanes[0];
      const unprotectedLane = [0, 1, 2].find((lane) => !phase.lanes.includes(lane));
      expect(movingTrainPhaseBlocksObstacle(phase, phase.start - 50, protectedLane, 0.6)).toBe(true);
      expect(movingTrainPhaseBlocksObstacle(phase, phase.end + 49, protectedLane, 0.6)).toBe(true);
      expect(movingTrainPhaseBlocksObstacle(phase, phase.end + 50, protectedLane, 0.6)).toBe(false);
      expect(movingTrainPhaseBlocksObstacle(phase, phase.start - 50.7, protectedLane, 0.6)).toBe(false);
      expect(movingTrainPhaseBlocksObstacle(phase, phase.start, unprotectedLane, 1)).toBe(false);
    }
    expect(threeTrainPhases).toBeGreaterThan(0);
    expect(threeTrainPhases).toBeLessThan(60);
  });

  it('starts moving trains at 20,000 score and schedules phases 400 to 500 meters apart', () => {
    expect(FIRST_MOVING_TRAIN_SCORE).toBe(20000);
    const rng = createRng(835);
    let previousStart = 3000;
    for (let i = 0; i < 100; i++) {
      const nextStart = nextMovingTrainPhaseStart(rng, previousStart);
      expect(nextStart - previousStart).toBeGreaterThanOrEqual(400);
      expect(nextStart - previousStart).toBeLessThan(500);
      previousStart = nextStart;
    }
  });

  it('leaves room after a train before the next row', () => {
    const rng = createRng(99);
    for (let i = 0; i < 2000; i++) {
      const trainDepth = 10 + rng() * 50;
      expect(nextRowGap(rng, 1, trainDepth)).toBeGreaterThan(trainDepth + 8);
    }
  });

  it('provides a front ramp, train roof, and abrupt drop at the rear', () => {
    const { depth, height, rampLength } = OBSTACLE_SPECS[OBSTACLE.TRAIN];
    expect(trainSurfaceHeight(-0.1)).toBe(0);
    expect(trainSurfaceHeight(0)).toBe(0);
    expect(trainSurfaceHeight(rampLength / 2)).toBeCloseTo(height / 2);
    expect(trainSurfaceHeight(rampLength)).toBe(height);
    expect(trainSurfaceHeight(depth / 2)).toBe(height);
    expect(trainSurfaceHeight(depth - 0.001)).toBe(height);
    expect(trainSurfaceHeight(depth)).toBe(0);
    expect(trainSurfaceHeight(depth + 0.1)).toBe(0);
    const longerTrain = { ...OBSTACLE_SPECS[OBSTACLE.TRAIN], depth: 14 };
    expect(trainSurfaceHeight(7, longerTrain)).toBe(longerTrain.height);
    const noFrontRamp = { ...OBSTACLE_SPECS[OBSTACLE.TRAIN], frontRamp: false };
    expect(trainSurfaceHeight(noFrontRamp.rampLength / 2, noFrontRamp)).toBe(0);
    expect(trainSurfaceHeight(noFrontRamp.rampLength, noFrontRamp)).toBe(noFrontRamp.height);
  });
});
