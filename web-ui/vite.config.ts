import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { outDir: '../src/pi_agent/web/static', emptyOutDir: true },
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8766', changeOrigin: false } } },
});
