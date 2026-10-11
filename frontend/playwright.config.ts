import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:7860',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1440, height: 1050 },
    screenshot: 'only-on-failure',
  },
});
