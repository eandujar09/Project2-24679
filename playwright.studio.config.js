import { defineConfig } from '@playwright/test';

const python = process.env.GRADIO_TEST_PYTHON || (process.platform === 'win32' ? '.venv-gradio/Scripts/python.exe' : '.venv-gradio/bin/python');
export default defineConfig({
  testDir: './tests/studio',
  outputDir: './test-results/studio-browser',
  timeout: 90000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:7862',
    viewport: { width: 1500, height: 1000 },
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
    screenshot: 'only-on-failure',
    actionTimeout: 15000,
  },
  webServer: {
    command: `"${python}" tests/serve_chat_fixture.py test-results/studio-workspace-${Date.now()} --studio`,
    url: 'http://127.0.0.1:7862',
    reuseExistingServer: false,
    timeout: 180000,
  },
});
