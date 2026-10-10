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
  [OBSTACLE.TRAIN]: { width: 2.1, height: 3.2, depth: 12, bottom: 0 },
};

const DIFFICULTY_RAMP_METERS = 2500;

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
    obstacles.push({ lane, type });
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

export function nextRowGap(rng, difficulty) {
  return 30 - 8 * difficulty + rng() * 8;
}
