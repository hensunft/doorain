import { defineConfig, devices } from '@playwright/test'

const PORT = 8765
export const E2E_PASSWORD = 'e2e passphrase 12345'

export default defineConfig({
  testDir: '../tests/e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure', locale: 'ru-RU' },
  webServer: {
    command: 'uv run python -m app.devserver',
    cwd: '../backend',
    url: `http://127.0.0.1:${PORT}/api/v1/health/live`,
    reuseExistingServer: false,
    timeout: 120_000,
    // весь набор идёт с одного IP подряд: рабочий лимит 300 запросов в минуту для стенда поднят
    env: { E2E_PASSWORD, E2E_DEMO: '1', E2E_PORT: String(PORT), PYTHONIOENCODING: 'utf-8', DOORAIN_API_RATE_PER_MINUTE: '3000' },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
})
