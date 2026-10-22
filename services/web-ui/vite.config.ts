import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Local ports from docs/implementation-notes.md §1.
const AGENT_API_URL = process.env.AGENT_API_URL ?? 'http://localhost:8000';
const FLEET_API_URL = process.env.FLEET_API_URL ?? 'http://localhost:8080';

// VITE_BASE lets the static demo live under a sub-path, e.g. /cohortex/ on GitHub Pages.
const base = process.env.VITE_BASE ?? '/';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/agent': {
        target: AGENT_API_URL,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/agent/, ''),
      },
      '/api/fleet': {
        target: FLEET_API_URL,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/fleet/, ''),
      },
    },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 900,
  },
});
