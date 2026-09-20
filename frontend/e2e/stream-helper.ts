import type { Page } from '@playwright/test'

// Chromium does not retain an SSE body for Network.getResponseBody. Tee the
// actual browser response without delaying delivery to the application.
export async function observeAgentStream(page: Page) {
  await page.evaluate(() => {
    const state = window as unknown as { observing?: boolean; agentStream?: Promise<string> }
    if (state.observing) return
    state.observing = true
    const original = window.fetch
    window.fetch = async (...args) => {
      const response = await original(...args)
      if (String(args[0]).endsWith('/messages/stream')) state.agentStream = response.clone().text()
      return response
    }
  })
}

export async function readAgentStream(page: Page) {
  await page.waitForFunction(() => Boolean((window as unknown as { agentStream?: Promise<string> }).agentStream))
  const text = await page.evaluate(() => (
    window as unknown as { agentStream: Promise<string> }
  ).agentStream)
  const terminal = text.split(/\r?\n\r?\n/).find((frame) => /^event: (result|error)/.test(frame))
  if (!terminal) throw new Error('Stream has no terminal frame')
  const data = JSON.parse(terminal.split('\n').find((line) => line.startsWith('data:'))!.slice(5))
  const failed = terminal.startsWith('event: error')
  return { ok: () => !failed, status: () => failed ? data.status : 200,
    json: async () => failed ? { error: data } : data }
}
