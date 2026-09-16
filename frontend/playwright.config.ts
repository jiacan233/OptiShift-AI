import { randomUUID } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { env } from 'node:process'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const frontendDirectory = fileURLToPath(new URL('.', import.meta.url))
const repositoryDirectory = fileURLToPath(new URL('..', import.meta.url))
const apiPort = 8001
const webPort = 4173
const apiUrl = `http://127.0.0.1:${apiPort}`
const webUrl = `http://127.0.0.1:${webPort}`
const databasePath = join(tmpdir(), `optishift-playwright-${randomUUID()}.db`)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: webUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `${env.PYTHON_EXECUTABLE ?? 'python'} -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: repositoryDirectory,
      env: {
        ...env,
        DATABASE_URL: databasePath,
        CORS_ORIGINS: webUrl,
      },
      url: `${apiUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
      cwd: frontendDirectory,
      env: {
        ...env,
        VITE_API_BASE_URL: apiUrl,
      },
      url: webUrl,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
})
