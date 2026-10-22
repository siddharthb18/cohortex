import { defineConfig, devices } from '@playwright/test';

// Use the pre-installed Chromium; never download browsers (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1).
const executablePath = process.env.PW_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium';
const CI = Boolean(process.env.CI);
const SCREENSHOTS = Boolean(process.env.SCREENSHOTS);

const APP_URL = 'http://127.0.0.1:4173';
const DEMO_URL = 'http://127.0.0.1:4174/cohortex/';

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    ...devices['Desktop Chrome'],
    launchOptions: { executablePath },
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'app',
      testIgnore: [/demo\.spec\.ts/, /screenshots\.spec\.ts/],
      use: { baseURL: APP_URL },
    },
    {
      name: 'demo',
      testMatch: /demo\.spec\.ts/,
      use: { baseURL: DEMO_URL },
    },
    ...(SCREENSHOTS
      ? [
          {
            name: 'screenshots',
            testMatch: /screenshots\.spec\.ts/,
            use: { baseURL: DEMO_URL, viewport: { width: 1360, height: 900 } },
          },
        ]
      : []),
  ],
  // Production builds served by `vite preview`; APIs are mocked per test with page.route.
  webServer: [
    {
      command:
        'npx vite build --outDir .e2e/app --logLevel warn && npx vite preview --outDir .e2e/app --host 127.0.0.1 --port 4173 --strictPort',
      url: APP_URL,
      reuseExistingServer: !CI,
      timeout: 180_000,
    },
    {
      command:
        'VITE_DEMO=1 VITE_BASE=/cohortex/ npx vite build --outDir .e2e/demo --logLevel warn && VITE_BASE=/cohortex/ npx vite preview --outDir .e2e/demo --host 127.0.0.1 --port 4174 --strictPort',
      url: DEMO_URL,
      reuseExistingServer: !CI,
      timeout: 180_000,
    },
  ],
});
