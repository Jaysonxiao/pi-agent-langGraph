import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1,
  globalSetup: './e2e/setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:8776', viewport: { width: 1440, height: 960 },
    trace: 'retain-on-failure',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  },
});
