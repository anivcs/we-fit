import { defineConfig } from 'vite';

export default defineConfig({
  server: { port: 5173 },
  // Three.js alone is ~500 kB minified; the game is served from the local network, so one bundle is fine.
  build: { chunkSizeWarningLimit: 800 },
});
