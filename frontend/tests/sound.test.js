import { describe, expect, it, vi } from 'vitest';

import { createSounds } from '../src/sound.js';

function fakeAudio(play) {
  const instances = [];
  class FakeAudio {
    currentTime = 0;
    constructor(src) {
      this.src = src;
      this.play = play ?? vi.fn(() => Promise.resolve());
      instances.push(this);
    }
  }
  return { FakeAudio, instances };
}

describe('sounds', () => {
  it('plays the death clip from the start every time', () => {
    const { FakeAudio, instances } = fakeAudio();
    const sounds = createSounds(FakeAudio);
    const [death] = instances;
    expect(death.src).toContain('death');

    death.currentTime = 0.8;
    sounds.playDeath();
    expect(death.currentTime).toBe(0);
    expect(death.play).toHaveBeenCalledTimes(1);

    sounds.playDeath();
    expect(death.play).toHaveBeenCalledTimes(2);
  });

  it('does not throw when the browser blocks playback', async () => {
    const { FakeAudio } = fakeAudio(() => Promise.reject(new DOMException('blocked', 'NotAllowedError')));
    const sounds = createSounds(FakeAudio);
    expect(() => sounds.playDeath()).not.toThrow();
    await Promise.resolve();
  });

  it('is silent when the browser has no Audio', () => {
    expect(() => createSounds(undefined).playDeath()).not.toThrow();
  });
});
