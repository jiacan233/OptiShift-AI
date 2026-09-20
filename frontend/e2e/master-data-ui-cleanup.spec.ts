import { expect, test } from '@playwright/test'

const TEST_WEEK = '2026-09-14'
const schedule = {
  schedule_id: 'layout_read_only_fixture',
  version: 1,
  parent_schedule_id: null,
  status: 'draft',
  week_start: TEST_WEEK,
  assignments: [],
  created_at: '2026-09-20T00:00:00Z',
}
const validation = {
  passed: true,
  valid: true,
  confirmable: true,
  compliance_status: 'compliant',
  violations: [],
  authorized_violations: [],
  unauthorized_violations: [],
  protected_violations: [],
  integrity_violations: [],
  coverage: [],
  total: 10,
  passed_count: 10,
  checks: [],
}
const result = {
  status: 'feasible',
  schedule_id: schedule.schedule_id,
  version: schedule.version,
  schedule_status: schedule.status,
  schedule,
  validation,
  compliance_status: 'compliant',
  confirmable: true,
  metrics: { preference_rate: 0, workload_gap: 0, changed_assignments: 0 },
  diff: null,
  impact: null,
  warnings: [],
  explanation: null,
}

test('固定员工 roster 与排班页清理在桌面端保持生效', async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 900 })

  await page.route('**/api/schedules/latest?**', async (route) => {
    const status = new URL(route.request().url()).searchParams.get('status')
    await route.fulfill({ json: status === 'draft' ? schedule : null })
  })
  await page.route('**/api/schedules/week-context?**', async (route) => {
    await route.fulfill({
      json: {
        week_start: TEST_WEEK,
        confirmed_schedule: null,
        draft_schedule: schedule,
        display_schedule: schedule,
        versions: [{ ...schedule, assignments: undefined }],
        result,
      },
    })
  })
  await page.route('**/api/schedule/validate', async (route) => {
    await route.fulfill({ json: result })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '排班工作台' })).toBeVisible()
  await expect(page.getByText(/^20 \/ 20 员工$/)).toBeVisible()
  await expect(page.getByText(/调班申请待确认|Swap requested/i)).toHaveCount(0)

  const leftColumn = page.locator('[data-schedule-grid-container]')
  const attendanceHeading = leftColumn.getByRole('heading', { name: '本周人员安排' })
  const activityHeading = leftColumn.getByRole('heading', { name: '最近排班版本' })
  await expect(attendanceHeading).toBeVisible()
  await expect(activityHeading).toBeVisible()
  await expect(page.getByRole('heading', { name: '本周运营概览' })).toBeVisible()

  const layout = await leftColumn.evaluate((column) => {
    const headings = Array.from(column.querySelectorAll('h3'))
    const attendance = headings.find((heading) => heading.textContent?.trim() === '本周人员安排')
    const activity = headings.find((heading) => heading.textContent?.trim() === '最近排班版本')
    const companion = attendance?.closest('section')?.parentElement
    const scheduleElement = companion?.previousElementSibling
    const gap = companion && scheduleElement
      ? companion.getBoundingClientRect().top - scheduleElement.getBoundingClientRect().bottom
      : null

    return {
      cardsShareCompanion: activity?.closest('section')?.parentElement === companion,
      companionIsInLeftFlow: companion?.parentElement === column,
      followsSchedule: scheduleElement?.textContent?.includes('员工排班') ?? false,
      gap,
    }
  })

  expect(layout.cardsShareCompanion).toBeTruthy()
  expect(layout.companionIsInLeftFlow).toBeTruthy()
  expect(layout.followsSchedule).toBeTruthy()
  expect(layout.gap).not.toBeNull()
  expect(layout.gap!).toBeGreaterThanOrEqual(0)
  expect(layout.gap!).toBeLessThanOrEqual(64)

  await page.getByRole('button', { name: '员工管理' }).click()
  await expect(page.getByRole('heading', { name: '员工管理' })).toBeVisible()
  await expect(page.getByText(/^20 \/ 20 名员工$/)).toBeVisible()
  await expect(page.getByRole('button', { name: '添加员工' })).toHaveCount(0)
})
