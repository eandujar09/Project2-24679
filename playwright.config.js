import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 90000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    viewport: { width: 1440, height: 960 },
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  webServer: {
    command: `${process.platform === 'win32' ? 'npm.cmd' : 'npm'} run preview -- --port 4173 --strictPort`,
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
  },
});
