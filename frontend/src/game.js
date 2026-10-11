import * as THREE from 'three';

import deathSoundUrl from './assets/death.mp3?url';
import { MOVES } from './moves.js';
import { createRng } from './rng.js';
import {
  LANES,
  OBSTACLE,
  OBSTACLE_SPECS,
  canLandOnTrain,
  difficultyAt,
  generateRow,
  nextRowGap,
  trainBlocksLaneChange,
  trainHasFrontRamp,
  trainSurfaceHeight,
} from './track.js';

export const SCORE_PER_METER = 10;
export const SCORE_PER_COIN = 100;

const START_SPEED = 14;
const MAX_SPEED = 32;
const ACCELERATION = 0.22;
const FIRST_ROW_AT = 45;
const SPAWN_AHEAD = 150;
const DESPAWN_BEHIND = 15;

const GRAVITY = 38;
const JUMP_VELOCITY = 12;
const LANE_CHANGE_SPEED = 18;
const DUCK_DURATION = 0.75;
const STAND_HEIGHT = 1.7;
const DUCK_HEIGHT = 0.8;
const PLAYER_HALF_WIDTH = 0.35;
const PLAYER_HALF_DEPTH = 0.35;
const COIN_PICKUP_RADIUS = 0.9;
const COIN_SPACING = 2.2;
const CAMERA_BASE_HEIGHT = 4.2;
const CAMERA_LOOK_AT_HEIGHT = 1.2;
const CAMERA_FOLLOW_SPEED = 4.5;
const DEATH_ANIMATION_SECONDS = 1;
const DEATH_LUNGE_SECONDS = 0.18;

const TRACK_TILE_METERS = 8;
const SCENERY_SPAN = 240;
const BUILDINGS_PER_SIDE = 24;

export function scoreFor(distance, coins) {
  return Math.floor(distance) * SCORE_PER_METER + coins * SCORE_PER_COIN;
}

function rangesOverlap(aMin, aMax, bMin, bMax) {
  return aMin < bMax && bMin < aMax;
}

function makeTrackTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#6b6259';
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = '#4a3a2c';
  for (let y = 0; y < 256; y += 64) ctx.fillRect(0, y, 256, 18);
  ctx.fillStyle = '#c9ccd1';
  for (const x of [44, 76, 116, 140, 180, 212]) ctx.fillRect(x - 3, 0, 6, 256);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export class Game {
  constructor(container, { onUpdate, onGameOver }) {
    this.container = container;
    this.onUpdate = onUpdate;
    this.onGameOver = onGameOver;
    this.state = 'idle';
    this.obstacles = [];
    this.coinsInWorld = [];
    this.lastTime = null;
    this.elapsed = 0;
    this.deathAnimation = null;
    this.deathAudio = new Audio(deathSoundUrl);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#8fd3ff');
    this.scene.fog = new THREE.Fog('#8fd3ff', 60, 150);

    this.camera = new THREE.PerspectiveCamera(65, 1, 0.1, 300);
    this.camera.position.set(0, 4.2, 7.5);

    this.scene.add(new THREE.HemisphereLight('#ffffff', '#5a6b4a', 1.6));
    const sun = new THREE.DirectionalLight('#ffffff', 1.8);
    sun.position.set(-6, 12, 6);
    this.scene.add(sun);

    this.buildMaterials();
    this.buildTrack();
    this.buildScenery();
    this.buildPlayer();

    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.renderer.setAnimationLoop((time) => this.tick(time));
  }

  buildMaterials() {
    const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.7, ...extra });
    this.materials = {
      low: mat('#e63946'),
      lowStripe: mat('#ffffff'),
      high: mat('#f4a261'),
      post: mat('#3d405b'),
      train: mat('#2a9d8f'),
      trainWindow: mat('#cfe8ef', { emissive: '#335566', emissiveIntensity: 0.3 }),
      coin: mat('#ffd60a', { metalness: 0.6, roughness: 0.3, emissive: '#7a5c00', emissiveIntensity: 0.4 }),
      body: mat('#4361ee'),
      skin: mat('#f1c27d'),
      legs: mat('#22223b'),
      shadow: new THREE.MeshBasicMaterial({ color: '#000000', transparent: true, opacity: 0.25 }),
    };
    this.geometries = {
      box: new THREE.BoxGeometry(1, 1, 1),
      coin: new THREE.CylinderGeometry(0.35, 0.35, 0.08, 20).rotateX(Math.PI / 2),
    };
  }

  box(material, w, h, d) {
    const mesh = new THREE.Mesh(this.geometries.box, material);
    mesh.scale.set(w, h, d);
    return mesh;
  }

  buildTrack() {
    this.trackTexture = makeTrackTexture();
    const length = 300;
    this.trackTexture.repeat.set(1, length / TRACK_TILE_METERS);
    const track = new THREE.Mesh(
      new THREE.PlaneGeometry(8, length),
      new THREE.MeshStandardMaterial({ map: this.trackTexture, roughness: 0.9 }),
    );
    track.rotation.x = -Math.PI / 2;
    track.position.z = -length / 2 + 20;
    this.scene.add(track);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 300),
      new THREE.MeshStandardMaterial({ color: '#7fb069', roughness: 1 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(0, -0.02, -130);
    this.scene.add(ground);
  }

  buildScenery() {
    const palette = ['#e9c46a', '#f4a261', '#e76f51', '#a8dadc', '#b5838d', '#ffb4a2', '#cdb4db'];
    this.buildings = [];
    for (const side of [-1, 1]) {
      for (let i = 0; i < BUILDINGS_PER_SIDE; i++) {
        const w = 4 + Math.random() * 4;
        const h = 5 + Math.random() * 14;
        const d = 6 + Math.random() * 4;
        const material = new THREE.MeshStandardMaterial({ color: palette[i % palette.length], roughness: 0.9 });
        const mesh = this.box(material, w, h, d);
        mesh.position.set(side * (8 + w / 2 + Math.random() * 3), h / 2, 0);
        this.scene.add(mesh);
        this.buildings.push({ mesh, at: (i / BUILDINGS_PER_SIDE) * SCENERY_SPAN - 20 });
      }
    }
  }

  buildPlayer() {
    const { body, skin, legs, shadow } = this.materials;
    const player = new THREE.Group();
    const torso = this.box(body, 0.7, 0.8, 0.45);
    torso.position.y = 1.05;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.25, 16, 12), skin);
    head.position.y = 1.7 - 0.25;
    const leftLeg = this.box(legs, 0.24, 0.65, 0.3);
    const rightLeg = this.box(legs, 0.24, 0.65, 0.3);
    for (const [leg, x] of [[leftLeg, -0.18], [rightLeg, 0.18]]) {
      leg.position.set(x, 0.33, 0);
      player.add(leg);
    }
    player.add(torso, head);
    this.scene.add(player);

    const blob = new THREE.Mesh(new THREE.CircleGeometry(0.5, 20), shadow);
    blob.rotation.x = -Math.PI / 2;
    blob.position.y = 0.01;
    this.scene.add(blob);

    this.playerMesh = player;
    this.playerLegs = [leftLeg, rightLeg];
    this.playerShadow = blob;
  }

  createObstacleMesh(type, spec = OBSTACLE_SPECS[type]) {
    const group = new THREE.Group();
    if (type === OBSTACLE.LOW) {
      const barrier = this.box(this.materials.low, spec.width, spec.height, spec.depth);
      barrier.position.y = spec.height / 2;
      const stripe = this.box(this.materials.lowStripe, spec.width + 0.01, 0.15, spec.depth + 0.01);
      stripe.position.y = spec.height * 0.6;
      group.add(barrier, stripe);
    } else if (type === OBSTACLE.HIGH) {
      const bar = this.box(this.materials.high, spec.width, spec.height, spec.depth);
      bar.position.y = spec.bottom + spec.height / 2;
      group.add(bar);
      const postHeight = spec.bottom + spec.height;
      for (const x of [-spec.width / 2, spec.width / 2]) {
        const post = this.box(this.materials.post, 0.12, postHeight, 0.12);
        post.position.set(x, postHeight / 2, 0);
        group.add(post);
      }
    } else {
      const hasFrontRamp = spec.frontRamp !== false;
      const bodyDepth = spec.depth - (hasFrontRamp ? spec.rampLength : 0);
      const car = this.box(this.materials.train, spec.width, spec.height, bodyDepth);
      car.position.y = spec.height / 2;
      if (hasFrontRamp) car.position.z = -spec.rampLength / 2;
      group.add(car);
      const rampLength = Math.hypot(spec.rampLength, spec.height);
      const rampAngle = Math.atan2(spec.height, spec.rampLength);
      const rampOffset = spec.depth / 2 - spec.rampLength / 2;
      const frontRamp = hasFrontRamp ? this.box(this.materials.train, spec.width, 0.18, rampLength) : null;
      if (frontRamp) {
        frontRamp.position.set(0, spec.height / 2, rampOffset);
        frontRamp.rotation.x = rampAngle;
      }
      if (frontRamp) group.add(frontRamp);
      for (const x of [-spec.width / 2, spec.width / 2]) {
        const windows = this.box(this.materials.trainWindow, 0.02, 0.7, bodyDepth * 0.85);
        windows.position.set(x, spec.height * 0.65, car.position.z);
        group.add(windows);
      }
      const front = this.box(this.materials.trainWindow, spec.width * 0.7, 0.9, 0.02);
      front.position.set(0, spec.height * 0.65, car.position.z + bodyDepth / 2);
      group.add(front);
    }
    return group;
  }

  resize() {
    const { clientWidth: width, clientHeight: height } = this.container;
    this.renderer.setSize(width, height);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  clearWorld() {
    for (const item of [...this.obstacles, ...this.coinsInWorld]) this.scene.remove(item.mesh);
    this.obstacles = [];
    this.coinsInWorld = [];
  }

  reset(seed) {
    this.clearWorld();
    this.rng = createRng(seed);
    this.distance = 0;
    this.speed = START_SPEED;
    this.coins = 0;
    this.nextRowAt = FIRST_ROW_AT;
    this.deathAnimation = null;
    this.player = { lane: 1, x: LANES[1], y: 0, vy: 0, grounded: true, duckTimer: 0 };
    this.cameraFollowY = 0;
    this.camera.position.y = CAMERA_BASE_HEIGHT;
    this.state = 'ready';
    this.spawnAhead();
    this.syncMeshes();
    this.emitUpdate();
  }

  start() {
    if (this.state === 'ready') this.state = 'running';
  }

  setPaused(paused) {
    if (paused && this.state === 'running') this.state = 'paused';
    else if (!paused && this.state === 'paused') this.state = 'running';
  }

  // Returns true if the move changed the player's state, so callers only report real moves.
  handleMove(move) {
    if (this.state !== 'running') return false;
    const p = this.player;
    switch (move) {
      case MOVES.LEFT:
        if (p.lane === 0) return false;
        const leftTrain = p.grounded && p.y <= 0.05 ? this.trainBlockingLaneChange(p.lane - 1) : null;
        if (leftTrain) {
          this.endRun(leftTrain);
          return false;
        }
        p.lane -= 1;
        return true;
      case MOVES.RIGHT:
        if (p.lane === LANES.length - 1) return false;
        const rightTrain = p.grounded && p.y <= 0.05 ? this.trainBlockingLaneChange(p.lane + 1) : null;
        if (rightTrain) {
          this.endRun(rightTrain);
          return false;
        }
        p.lane += 1;
        return true;
      case MOVES.JUMP:
        if (!p.grounded) return false;
        p.vy = JUMP_VELOCITY;
        p.grounded = false;
        p.duckTimer = 0;
        return true;
      case MOVES.DUCK:
        if (!p.grounded) p.vy = -JUMP_VELOCITY;
        p.duckTimer = DUCK_DURATION;
        return true;
      default:
        return false;
    }
  }

  spawnAhead() {
    while (this.nextRowAt < this.distance + SPAWN_AHEAD) {
      const difficulty = difficultyAt(this.nextRowAt);
      const row = generateRow(this.rng, difficulty);
      for (const { lane, type, spec: generatedSpec } of row.obstacles) {
        let spec = generatedSpec ?? OBSTACLE_SPECS[type];
        if (type === OBSTACLE.TRAIN) {
          spec = { ...spec, frontRamp: trainHasFrontRamp(this.rng) };
        }
        const mesh = this.createObstacleMesh(type, spec);
        mesh.position.x = LANES[lane];
        this.scene.add(mesh);
        this.obstacles.push({ type, lane, at: this.nextRowAt, spec, mesh });
      }
      for (const { lane, height, count } of row.coins) {
        for (let i = 0; i < count; i++) {
          const mesh = new THREE.Mesh(this.geometries.coin, this.materials.coin);
          mesh.position.set(LANES[lane], height, 0);
          this.scene.add(mesh);
          const offset = (i - (count - 1) / 2) * COIN_SPACING;
          this.coinsInWorld.push({ lane, at: this.nextRowAt + offset, height, mesh });
        }
      }
      const trainDepth = row.obstacles.find((obstacle) => obstacle.type === OBSTACLE.TRAIN)?.spec.depth ?? 0;
      this.nextRowAt += nextRowGap(this.rng, difficulty, trainDepth);
    }
  }

  playerHeight() {
    return this.player.duckTimer > 0 ? DUCK_HEIGHT : STAND_HEIGHT;
  }

  trainBlockingLaneChange(targetLane) {
    const p = this.player;
    return this.obstacles.find((train) =>
      train.type === OBSTACLE.TRAIN &&
      trainBlocksLaneChange(this.distance, p.lane, targetLane, train, PLAYER_HALF_DEPTH),
    ) ?? null;
  }

  endRun(train = null) {
    if (this.state === 'over' || this.state === 'dying') return;
    this.deathAudio.currentTime = 0;
    const playback = this.deathAudio.play();
    if (playback) playback.catch((error) => console.warn('Unable to play death sound:', error));

    const p = this.player;
    const side = train ? Math.sign(LANES[train.lane] - p.x) : 0;
    this.deathAnimation = {
      elapsed: 0,
      startX: p.x,
      targetX: train ? LANES[train.lane] + side * (train.spec.width / 2 + 0.08) : p.x,
      fallDirection: side || 1,
      score: scoreFor(this.distance, this.coins),
      coins: this.coins,
      distance: Math.floor(this.distance),
    };
    this.state = 'dying';
  }

  updateDeath(dt) {
    const death = this.deathAnimation;
    death.elapsed = Math.min(DEATH_ANIMATION_SECONDS, death.elapsed + dt);
    const lunge = Math.min(1, death.elapsed / DEATH_LUNGE_SECONDS);
    const easedLunge = lunge * lunge * (3 - 2 * lunge);
    this.player.x = death.startX + (death.targetX - death.startX) * easedLunge;

    if (death.elapsed === DEATH_ANIMATION_SECONDS) {
      this.state = 'over';
      this.onGameOver?.({
        score: death.score,
        coins: death.coins,
        distance: death.distance,
      });
    }
  }

  update(dt) {
    const p = this.player;
    this.speed = Math.min(MAX_SPEED, this.speed + ACCELERATION * dt);
    this.distance += this.speed * dt;
    this.spawnAhead();

    const targetX = LANES[p.lane];
    const step = LANE_CHANGE_SPEED * dt;
    p.x = Math.abs(targetX - p.x) <= step ? targetX : p.x + Math.sign(targetX - p.x) * step;

    const groundY = this.groundHeightAt(this.distance, p.x, p.y, p.grounded);
    if (p.grounded && groundY < p.y) p.grounded = false;
    if (p.grounded) {
      p.y = groundY;
      p.vy = 0;
    } else {
      p.vy -= GRAVITY * dt;
      p.y += p.vy * dt;
      if (p.vy <= 0 && p.y <= groundY) {
        p.y = groundY;
        p.vy = 0;
        p.grounded = true;
      }
    }
    p.duckTimer = Math.max(0, p.duckTimer - dt);

    if (this.checkCollision()) {
      this.endRun();
      return;
    }

    this.collectCoins();
    this.despawn();
    this.emitUpdate();
  }

  checkCollision() {
    const p = this.player;
    const top = p.y + this.playerHeight();
    return this.obstacles.some(({ type, at, lane, spec }) => {
      if (type === OBSTACLE.TRAIN) {
        if (spec.frontRamp !== false) return false;
        const touchesFront =
          this.distance + PLAYER_HALF_DEPTH > at &&
          this.distance - PLAYER_HALF_DEPTH < at + PLAYER_HALF_DEPTH;
        if (!touchesFront || p.y >= spec.height) return false;
      }
      if (
        !rangesOverlap(this.distance - PLAYER_HALF_DEPTH, this.distance + PLAYER_HALF_DEPTH, at, at + spec.depth) ||
        Math.abs(p.x - LANES[lane]) >= PLAYER_HALF_WIDTH + spec.width / 2
      ) return false;
      return rangesOverlap(p.y, top, spec.bottom, spec.bottom + spec.height);
    });
  }

  groundHeightAt(distance, x, playerY = 0, grounded = true) {
    return this.obstacles.reduce((height, obstacle) => {
      if (
        obstacle.type !== OBSTACLE.TRAIN ||
        Math.abs(x - LANES[obstacle.lane]) >= PLAYER_HALF_WIDTH + obstacle.spec.width / 2
      ) return height;
      const surface = trainSurfaceHeight(distance - obstacle.at, obstacle.spec);
      if (!canLandOnTrain(playerY, surface, grounded)) return height;
      return Math.max(height, surface);
    }, 0);
  }

  collectCoins() {
    const p = this.player;
    const top = p.y + this.playerHeight();
    this.coinsInWorld = this.coinsInWorld.filter((coin) => {
      const hit =
        Math.abs(coin.at - this.distance) < COIN_PICKUP_RADIUS &&
        Math.abs(p.x - LANES[coin.lane]) < COIN_PICKUP_RADIUS &&
        coin.height > p.y - 0.3 &&
        coin.height < top + 0.3;
      if (hit) {
        this.coins += 1;
        this.scene.remove(coin.mesh);
      }
      return !hit;
    });
  }

  despawn() {
    const behind = this.distance - DESPAWN_BEHIND;
    const keep = (item) => {
      const end = item.at + (item.spec?.depth ?? 0);
      if (end >= behind) return true;
      this.scene.remove(item.mesh);
      return false;
    };
    this.obstacles = this.obstacles.filter(keep);
    this.coinsInWorld = this.coinsInWorld.filter(keep);
  }

  emitUpdate() {
    this.onUpdate?.({
      score: scoreFor(this.distance, this.coins),
      coins: this.coins,
      distance: Math.floor(this.distance),
      speed: this.speed,
    });
  }

  // World objects are stored by track distance; the player stays at z=0 and the world moves toward the camera.
  syncMeshes(dt = 0) {
    const toZ = (at) => -(at - this.distance);
    for (const { at, spec, mesh } of this.obstacles) mesh.position.z = toZ(at + spec.depth / 2);
    for (const coin of this.coinsInWorld) {
      coin.mesh.position.z = toZ(coin.at);
      coin.mesh.rotation.y = this.elapsed * 4;
    }
    for (const building of this.buildings) {
      while (toZ(building.at) > 20) building.at += SCENERY_SPAN;
      building.mesh.position.z = toZ(building.at);
    }
    this.trackTexture.offset.y = this.distance / TRACK_TILE_METERS;

    const p = this.player;
    const ducking = p.duckTimer > 0;
    this.playerMesh.position.set(p.x, p.y, 0);
    this.playerMesh.scale.y = ducking ? DUCK_HEIGHT / STAND_HEIGHT : 1;
    if (this.deathAnimation) {
      const deathProgress = Math.max(
        0,
        Math.min(1, (this.deathAnimation.elapsed - DEATH_LUNGE_SECONDS) / (DEATH_ANIMATION_SECONDS - DEATH_LUNGE_SECONDS)),
      );
      this.playerMesh.rotation.x = 0;
      this.playerMesh.rotation.z = -this.deathAnimation.fallDirection * deathProgress * Math.PI / 2;
    } else {
      this.playerMesh.rotation.x = this.state === 'over' ? -0.5 : 0;
      this.playerMesh.rotation.z = 0;
    }
    const stride = this.state === 'running' && p.grounded ? Math.sin(this.elapsed * this.speed * 0.9) * 0.6 : 0;
    this.playerLegs[0].rotation.x = stride;
    this.playerLegs[1].rotation.x = -stride;
    this.playerShadow.position.x = p.x;
    this.playerShadow.position.y = this.groundHeightAt(this.distance, p.x, p.y, p.grounded) + 0.01;
    this.playerShadow.scale.setScalar(Math.max(0.4, 1 - p.y * 0.25));

    const cameraFollow = 1 - Math.exp(-CAMERA_FOLLOW_SPEED * dt);
    const onTrain = this.groundHeightAt(this.distance, p.x, p.y, p.grounded) > 0;
    const cameraTargetY = !p.grounded || onTrain ? p.y : 0;
    this.cameraFollowY += (cameraTargetY - this.cameraFollowY) * cameraFollow;
    this.camera.position.x += (p.x * 0.5 - this.camera.position.x) * 0.1;
    this.camera.position.y = CAMERA_BASE_HEIGHT + this.cameraFollowY;
    this.camera.lookAt(p.x * 0.3, CAMERA_LOOK_AT_HEIGHT + this.cameraFollowY, -10);
  }

  tick(time) {
    const dt = this.lastTime === null ? 0 : Math.min((time - this.lastTime) / 1000, 0.05);
    this.lastTime = time;
    this.elapsed += dt;
    if (this.state === 'running') this.update(dt);
    if (this.state === 'dying') this.updateDeath(dt);
    if (this.player) this.syncMeshes(dt);
    this.renderer.render(this.scene, this.camera);
  }
}
