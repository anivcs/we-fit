import { createApi, generateId, userIdFromName } from './api.js';
import { API_BASE_URL, CONTROLLER_URL } from './config.js';
import { connectController } from './controller.js';
import { Game } from './game.js';
import { attachKeyboard, attachSwipe } from './input.js';
import { MOVES } from './moves.js';
import { randomSeed } from './rng.js';

const NAME_STORAGE_KEY = 'wefit.playerName';
const HEALTH_POLL_MS = 15000;
const COUNTDOWN_SECONDS = 3;
// Players are often mid-jump when they crash; don't let that jump restart the game instantly.
const RESTART_LOCKOUT_MS = 1500;

const $ = (id) => document.getElementById(id);
const ui = {
  scene: $('scene'),
  backendStatus: $('backend-status'),
  controllerStatus: $('controller-status'),
  hud: $('hud'),
  hudScore: $('hud-score'),
  hudCoins: $('hud-coins'),
  hudDistance: $('hud-distance'),
  countdown: $('countdown'),
  paused: $('paused'),
  overlay: $('overlay'),
  menu: $('menu'),
  nameInput: $('player-name'),
  playBtn: $('play-btn'),
  playerStats: $('player-stats'),
  gameover: $('gameover'),
  resultScore: $('result-score'),
  resultCoins: $('result-coins'),
  resultDistance: $('result-distance'),
  highScore: $('high-score'),
  saveStatus: $('save-status'),
  againBtn: $('again-btn'),
  menuBtn: $('menu-btn'),
  leaderboardList: $('leaderboard-list'),
  leaderboardEmpty: $('leaderboard-empty'),
  tabs: document.querySelectorAll('.tabs button'),
};

const api = createApi(API_BASE_URL);
const formatNumber = (n) => n.toLocaleString();

// 'menu' | 'countdown' | 'playing' | 'paused' | 'over'
let appState = 'menu';
let session = null;
let timeframe = 'all_time';
let gameOverAt = 0;

const game = new Game(ui.scene, {
  onUpdate: ({ score, coins, distance }) => {
    ui.hudScore.textContent = formatNumber(score);
    ui.hudCoins.textContent = formatNumber(coins);
    ui.hudDistance.textContent = `${formatNumber(distance)} m`;
  },
  onGameOver: handleGameOver,
  onMove: reportMove,
});
game.reset(randomSeed());

function setPill(el, text, tone) {
  el.textContent = text;
  el.dataset.tone = tone;
}

function showOverlay(panel) {
  ui.overlay.hidden = panel === null;
  ui.menu.hidden = panel !== 'menu';
  ui.gameover.hidden = panel !== 'gameover';
  ui.hud.hidden = panel !== null && panel !== 'gameover';
}

async function checkBackend() {
  try {
    const health = await api.healthCheck();
    const ok = health.status === 'healthy';
    setPill(ui.backendStatus, ok ? 'Backend: online' : 'Backend: database down', ok ? 'ok' : 'warn');
    return ok;
  } catch {
    setPill(ui.backendStatus, 'Backend: offline (scores not saved)', 'error');
    return false;
  }
}

async function refreshLeaderboard() {
  try {
    const { rankings } = await api.getLeaderboard({ limit: 10, timeframe });
    ui.leaderboardList.replaceChildren(
      ...rankings.map(({ rank, username, score }) => {
        const li = document.createElement('li');
        const name = document.createElement('span');
        name.textContent = `${rank}. ${username}`;
        const points = document.createElement('strong');
        points.textContent = formatNumber(score);
        li.append(name, points);
        return li;
      }),
    );
    ui.leaderboardEmpty.hidden = rankings.length > 0;
    ui.leaderboardEmpty.textContent = 'No scores yet. Enter a name and be the first!';
  } catch {
    ui.leaderboardList.replaceChildren();
    ui.leaderboardEmpty.hidden = false;
    ui.leaderboardEmpty.textContent = 'Leaderboard unavailable while the backend is offline.';
  }
}

async function refreshPlayerStats() {
  const userId = userIdFromName(ui.nameInput.value);
  ui.playerStats.hidden = true;
  if (!userId) return;
  try {
    const stats = await api.getUserStats(userId);
    if (!stats || userId !== userIdFromName(ui.nameInput.value)) return;
    ui.playerStats.textContent =
      `Best ${formatNumber(stats.highest_score)} · ${stats.total_games_played} games · ` +
      `${formatNumber(stats.total_coins)} coins · ${formatNumber(stats.total_distance)} m`;
    ui.playerStats.hidden = false;
  } catch {
    // Stats are a nice-to-have; the menu works without them.
  }
}

function runCountdown() {
  return new Promise((resolve) => {
    let remaining = COUNTDOWN_SECONDS;
    ui.countdown.hidden = false;
    ui.countdown.textContent = remaining;
    const timer = setInterval(() => {
      remaining -= 1;
      if (remaining > 0) {
        ui.countdown.textContent = remaining;
        return;
      }
      clearInterval(timer);
      ui.countdown.textContent = 'Go!';
      setTimeout(() => (ui.countdown.hidden = true), 500);
      resolve();
    }, 1000);
  });
}

async function startRun() {
  if (appState !== 'menu' && appState !== 'over') return;
  appState = 'countdown';
  document.activeElement?.blur();

  const username = ui.nameInput.value.trim();
  localStorage.setItem(NAME_STORAGE_KEY, username);
  const userId = userIdFromName(username);
  const sessionId = generateId('sess');

  let seed;
  let online = true;
  try {
    ({ seed } = await api.startGame({ sessionId, userId, username: username || undefined }));
  } catch {
    online = false;
    seed = randomSeed();
    setPill(ui.backendStatus, 'Backend: offline (scores not saved)', 'error');
  }
  session = { id: sessionId, online };

  game.reset(seed);
  showOverlay(null);
  ui.hud.hidden = false;
  await runCountdown();
  game.start();
  appState = 'playing';
}

async function handleGameOver({ score, coins, distance }) {
  appState = 'over';
  gameOverAt = performance.now();
  ui.resultScore.textContent = formatNumber(score);
  ui.resultCoins.textContent = formatNumber(coins);
  ui.resultDistance.textContent = `${formatNumber(distance)} m`;
  ui.highScore.hidden = true;
  showOverlay('gameover');

  if (!session?.online) {
    ui.saveStatus.textContent = 'Offline: this run was not saved.';
    return;
  }
  ui.saveStatus.textContent = 'Saving…';
  try {
    const result = await api.endGame({
      sessionId: session.id,
      finalScore: score,
      coinsCollected: coins,
      distanceTraveled: distance,
    });
    ui.highScore.hidden = !result.high_score_updated;
    ui.saveStatus.textContent = `Saved. +${result.earned_rewards.xp} XP, +${result.earned_rewards.coins} coins`;
  } catch (err) {
    ui.saveStatus.textContent = `Couldn't save this run (${err.message}).`;
  }
  refreshLeaderboard();
  refreshPlayerStats();
}

function togglePause() {
  if (appState === 'playing') {
    appState = 'paused';
    game.setPaused(true);
    ui.paused.hidden = false;
  } else if (appState === 'paused') {
    appState = 'playing';
    game.setPaused(false);
    ui.paused.hidden = true;
  }
}

function handleMove(move) {
  if (appState === 'menu' || appState === 'over') {
    const lockedOut = appState === 'over' && performance.now() - gameOverAt < RESTART_LOCKOUT_MS;
    if (move === MOVES.JUMP && !lockedOut) startRun();
    return;
  }
  if (appState !== 'playing') return;
  game.handleMove(move);
}

// Called by the game for every move that takes effect, including a jump that was buffered
// and ran on landing. Telemetry only: gameplay never waits on the network.
function reportMove(move) {
  if (session?.online) api.syncMove(session.id, move).catch(() => {});
}

function goToMenu() {
  if (appState !== 'over') return;
  appState = 'menu';
  showOverlay('menu');
  refreshPlayerStats();
}

attachKeyboard({ onMove: handleMove, onPause: togglePause });
attachSwipe(ui.scene, { onMove: handleMove });

if (CONTROLLER_URL) {
  const labels = { connecting: ['connecting…', 'warn'], connected: ['connected', 'ok'], disconnected: ['reconnecting…', 'error'] };
  connectController(CONTROLLER_URL, {
    onMove: handleMove,
    // tuning.toml [game], sent by the bridge on every (re)connect
    onSettings: ({ jumpBufferMs }) => {
      if (jumpBufferMs !== null) game.setJumpBufferMs(jumpBufferMs);
    },
    onStatus: (status) => setPill(ui.controllerStatus, `Controller: ${labels[status][0]}`, labels[status][1]),
  });
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden && appState === 'playing') togglePause();
});

ui.playBtn.addEventListener('click', startRun);
ui.againBtn.addEventListener('click', startRun);
ui.menuBtn.addEventListener('click', goToMenu);
ui.nameInput.value = localStorage.getItem(NAME_STORAGE_KEY) ?? '';
ui.nameInput.addEventListener('change', refreshPlayerStats);
ui.nameInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') startRun();
});
for (const tab of ui.tabs) {
  tab.addEventListener('click', () => {
    timeframe = tab.dataset.timeframe;
    ui.tabs.forEach((t) => t.classList.toggle('active', t === tab));
    refreshLeaderboard();
  });
}

showOverlay('menu');
checkBackend().then((ok) => {
  refreshLeaderboard();
  if (ok) refreshPlayerStats();
});
setInterval(() => {
  if (appState === 'menu' || appState === 'over') checkBackend();
}, HEALTH_POLL_MS);
