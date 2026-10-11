import deathUrl from './assets/death.mp3';

// Creates the Audio element up front so the first death doesn't wait on a download.
// `AudioImpl` is injectable for tests; browsers without Audio get a silent no-op.
export function createSounds(AudioImpl = globalThis.Audio) {
  if (!AudioImpl) return { playDeath() {} };

  const death = new AudioImpl(deathUrl);
  death.preload = 'auto';

  return {
    playDeath() {
      // Restart from the top so a quick second crash still plays the whole clip
      death.currentTime = 0;
      // Browsers reject play() until the page has had a click or key press; the player has
      // always pressed Play by the time they can die, but a lost sound must never break the game.
      death.play()?.catch(() => {});
    },
  };
}
