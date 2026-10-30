import { defineConfig } from '@playwright/test';

const python = process.platform === 'win32' ? '.\\.venv-gradio\\Scripts\\python.exe' : '.venv-gradio/bin/python';
export default defineConfig({
  testDir: './tests/gradio',
  outputDir: './test-results/gradio-browser',
  timeout: 90000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:7862',
    viewport: { width: 1500, height: 1100 },
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  webServer: {
    command: `"${python}" -m gradio_app.app --port 7862 --data-dir test-results/gradio-workspace-${Date.now()}`,
    url: 'http://127.0.0.1:7862',
    reuseExistingServer: false,
    timeout: 120000,
  },
});
