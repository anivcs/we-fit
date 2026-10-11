export const LANES = [-2.4, 0, 2.4];

export const OBSTACLE = Object.freeze({
  LOW: 'low', // jump over
  HIGH: 'high', // duck under
  TRAIN: 'train', // change lane
});

// Dimensions in meters. `bottom` is the height of the obstacle's underside above the track.
export const OBSTACLE_SPECS = {
  [OBSTACLE.LOW]: { width: 2.0, height: 0.9, depth: 0.6, bottom: 0 },
  [OBSTACLE.HIGH]: { width: 2.0, height: 1.3, depth: 0.6, bottom: 1.2 },
  [OBSTACLE.TRAIN]: { width: 2.1, height: 3.2, depth: 12, bottom: 0, rampLength: 4.2 },
};

const DIFFICULTY_RAMP_METERS = 2500;
const MIN_TRAIN_DEPTH = 10;
const MAX_TRAIN_DEPTH = 60;
const RAMPLESS_TRAIN_CHANCE = 0.4;

export function trainHasFrontRamp(rng) {
  return rng() >= RAMPLESS_TRAIN_CHANCE;
}

export function trainBlocksLaneChange(distance, fromLane, toLane, train, playerHalfDepth) {
  return (
    toLane === train.lane &&
    fromLane !== train.lane &&
    rangesOverlap(distance - playerHalfDepth, distance + playerHalfDepth, train.at, train.at + train.spec.depth)
  );
}

export function canLandOnTrain(playerY, trainHeight, grounded) {
  return grounded || playerY >= trainHeight - 0.5;
}

function rangesOverlap(aMin, aMax, bMin, bMax) {
  return aMin < bMax && bMin < aMax;
}

export function trainSurfaceHeight(distanceFromStart, spec = OBSTACLE_SPECS[OBSTACLE.TRAIN]) {
  if (distanceFromStart < 0 || distanceFromStart >= spec.depth) return 0;
  if (distanceFromStart < spec.rampLength) {
    return spec.frontRamp === false ? 0 : (spec.height * distanceFromStart) / spec.rampLength;
  }
  return spec.height;
}

export function difficultyAt(distance) {
  return Math.min(1, distance / DIFFICULTY_RAMP_METERS);
}

function shuffledLanes(rng) {
  const lanes = [0, 1, 2];
  for (let i = lanes.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [lanes[i], lanes[j]] = [lanes[j], lanes[i]];
  }
  return lanes;
}

// A row never blocks all three lanes and holds at most one train, so the player can always
// get through with at most one lane change.
export function generateRow(rng, difficulty) {
  const lanes = shuffledLanes(rng);
  const count = rng() < 0.35 + 0.35 * difficulty ? 2 : 1;
  const trainChance = 0.2 + 0.2 * difficulty;

  const obstacles = [];
  let hasTrain = false;
  for (const lane of lanes.slice(0, count)) {
    const roll = rng();
    let type;
    if (!hasTrain && roll < trainChance) {
      type = OBSTACLE.TRAIN;
      hasTrain = true;
    } else {
      type = rng() < 0.55 ? OBSTACLE.LOW : OBSTACLE.HIGH;
    }
    const spec = type === OBSTACLE.TRAIN
      ? { ...OBSTACLE_SPECS[type], depth: MIN_TRAIN_DEPTH + rng() * (MAX_TRAIN_DEPTH - MIN_TRAIN_DEPTH) }
      : OBSTACLE_SPECS[type];
    obstacles.push({ lane, type, ...(type === OBSTACLE.TRAIN ? { spec } : {}) });
  }

  const coins = [];
  const coinRoll = rng();
  if (coinRoll < 0.55) {
    coins.push({ lane: lanes[2], height: 1.0, count: 5 });
  } else if (coinRoll < 0.75) {
    const low = obstacles.find((o) => o.type === OBSTACLE.LOW);
    if (low) coins.push({ lane: low.lane, height: 2.0, count: 3 });
  }

  return { obstacles, coins };
}

export function nextRowGap(rng, difficulty, trainDepth = 0) {
  const regularGap = 30 - 8 * difficulty + rng() * 8;
  return trainDepth > 0 ? Math.max(regularGap, trainDepth + 8 + rng() * 8) : regularGap;
}
