import { randomUUID } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { env } from 'node:process'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

// Explicit opt-in keeps default CI offline and prevents accidental Provider spend.
if (env.OPTISHIFT_LIVE_BROWSER !== '1') throw new Error('Set OPTISHIFT_LIVE_BROWSER=1 to run real Provider browser acceptance.')
const root = fileURLToPath(new URL('..', import.meta.url))
if (!env.OPTISHIFT_LIVE_BASELINE_DIR) throw new Error('Set OPTISHIFT_LIVE_BASELINE_DIR to a prepared agent-multiturn-live baseline directory.')
const baseline = resolve(root, env.OPTISHIFT_LIVE_BASELINE_DIR)
for (const name of ['ordinary.db', 'fairness.db']) {
  if (!existsSync(resolve(baseline, name))) throw new Error(`Prepared baseline missing: ${name}`)
}
env.OPTISHIFT_LIVE_BASELINE_DIR = baseline
env.OPTISHIFT_LIVE_RUN_DIR ??= resolve(root, 'artifacts/agent-browser-live', `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`)
mkdirSync(env.OPTISHIFT_LIVE_RUN_DIR, { recursive: true })
const database = resolve(env.OPTISHIFT_LIVE_RUN_DIR, 'ordinary.db')
if (!existsSync(database)) copyFileSync(resolve(baseline, 'ordinary.db'), database)
env.OPTISHIFT_LIVE_API_PORT ??= '8127'
env.OPTISHIFT_LIVE_WEB_PORT ??= '4277'
const apiURL = `http://127.0.0.1:${env.OPTISHIFT_LIVE_API_PORT}`
const baseURL = `http://127.0.0.1:${env.OPTISHIFT_LIVE_WEB_PORT}`

export default defineConfig({
  testDir: './e2e-live',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 1_200_000,
  expect: { timeout: 20_000 },
  outputDir: resolve(env.OPTISHIFT_LIVE_RUN_DIR, 'browser'),
  reporter: [['list'], ['json', { outputFile: resolve(env.OPTISHIFT_LIVE_RUN_DIR, 'playwright-results.json') }]],
  use: { baseURL, trace: 'on', screenshot: 'on', actionTimeout: 30_000 },
  webServer: [
    {
      command: `${env.PYTHON_EXECUTABLE ?? 'python'} scripts/agent_multiturn_live.py --serve --case-dir "${env.OPTISHIFT_LIVE_RUN_DIR}" --port ${env.OPTISHIFT_LIVE_API_PORT}`,
      cwd: root,
      env: { ...env, APP_ENV: 'test', DATABASE_URL: database, LLM_ENABLED: 'true' },
      url: `${apiURL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${env.OPTISHIFT_LIVE_WEB_PORT} --strictPort`,
      cwd: fileURLToPath(new URL('.', import.meta.url)),
      env: { ...env, VITE_API_BASE_URL: apiURL },
      url: baseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [{ name: 'chromium-live', use: { ...devices['Desktop Chrome'] } }],
})
