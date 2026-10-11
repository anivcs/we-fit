import { describe, expect, it, vi } from 'vitest';

import { Game } from '../src/game.js';
import { createInputBuffer } from '../src/inputBuffer.js';

// Builds a Game without running its constructor, which needs WebGL and a DOM. Only the
// fields that move handling touches are filled in.
function makeGame(player = {}) {
  const game = Object.create(Game.prototype);
  Object.assign(game, {
    state: 'running',
    runTime: 0,
    inputBuffer: createInputBuffer(),
    onMove: vi.fn(),
    player: { lane: 1, y: 0, vy: 0, duckTimer: 0, ...player },
  });
  return game;
}

const AIRBORNE = { y: 1.5, vy: -4 };

describe('buffered jump', () => {
  it('jumps immediately when grounded', () => {
    const game = makeGame();
    expect(game.handleMove('JUMP')).toBe(true);
    expect(game.player.vy).toBeGreaterThan(0);
    expect(game.onMove).toHaveBeenCalledWith('JUMP');
  });

  it('holds a jump pressed in the air and runs it on landing', () => {
    const game = makeGame(AIRBORNE);
    game.runTime = 2.0;
    expect(game.handleMove('JUMP')).toBe(false);
    expect(game.onMove).not.toHaveBeenCalled();

    // Still in the air: nothing happens
    game.runTime = 2.05;
    game.flushBufferedMove();
    expect(game.onMove).not.toHaveBeenCalled();

    // Lands within the window
    Object.assign(game.player, { y: 0, vy: 0 });
    game.runTime = 2.1;
    game.flushBufferedMove();
    expect(game.player.vy).toBeGreaterThan(0);
    expect(game.onMove).toHaveBeenCalledTimes(1);
    expect(game.onMove).toHaveBeenCalledWith('JUMP');
  });

  it('forgets a jump pressed too early', () => {
    const game = makeGame(AIRBORNE);
    game.runTime = 2.0;
    game.handleMove('JUMP');
    Object.assign(game.player, { y: 0, vy: 0 });
    game.runTime = 2.5;
    game.flushBufferedMove();
    expect(game.player.vy).toBe(0);
    expect(game.onMove).not.toHaveBeenCalled();
  });

  it('does not jump twice from one press', () => {
    const game = makeGame(AIRBORNE);
    game.handleMove('JUMP');
    Object.assign(game.player, { y: 0, vy: 0 });
    game.flushBufferedMove();
    Object.assign(game.player, { y: 0, vy: 0 });
    game.flushBufferedMove();
    expect(game.onMove).toHaveBeenCalledTimes(1);
  });

  it('cancels the pending jump when the player ducks', () => {
    const game = makeGame(AIRBORNE);
    game.runTime = 2.0;
    game.handleMove('JUMP');
    expect(game.handleMove('DUCK')).toBe(true);
    Object.assign(game.player, { y: 0, vy: 0 });
    game.runTime = 2.05;
    game.flushBufferedMove();
    expect(game.player.vy).toBe(0);
    expect(game.onMove).toHaveBeenCalledTimes(1);
    expect(game.onMove).toHaveBeenCalledWith('DUCK');
  });

  it('keeps the pending jump when the player changes lane', () => {
    const game = makeGame(AIRBORNE);
    game.runTime = 2.0;
    game.handleMove('JUMP');
    expect(game.handleMove('LEFT')).toBe(true);
    expect(game.player.lane).toBe(0);
    Object.assign(game.player, { y: 0, vy: 0 });
    game.runTime = 2.1;
    game.flushBufferedMove();
    expect(game.onMove).toHaveBeenLastCalledWith('JUMP');
  });

  it('does not buffer a lane change against the edge lane', () => {
    const game = makeGame({ lane: 0 });
    expect(game.handleMove('LEFT')).toBe(false);
    expect(game.onMove).not.toHaveBeenCalled();
  });

  it('ignores moves while the game is not running', () => {
    const game = makeGame(AIRBORNE);
    game.state = 'paused';
    expect(game.handleMove('JUMP')).toBe(false);
    expect(game.inputBuffer.pending).toBeNull();
  });
});

describe('jump buffer setting', () => {
  it('sets the buffer window from milliseconds', () => {
    const game = Object.create(Game.prototype);
    game.inputBuffer = createInputBuffer();
    game.setJumpBufferMs(220);
    expect(game.inputBuffer.window).toBeCloseTo(0.22);
  });
});
