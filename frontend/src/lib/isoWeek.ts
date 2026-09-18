const DAY_MS = 24 * 60 * 60 * 1000

function parseDateOnly(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

function formatDateOnly(value: Date) {
  return [
    value.getUTCFullYear(),
    String(value.getUTCMonth() + 1).padStart(2, '0'),
    String(value.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

export function currentMonday() {
  const localToday = new Date()
  const date = new Date(Date.UTC(localToday.getFullYear(), localToday.getMonth(), localToday.getDate()))
  const offset = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - offset)
  return formatDateOnly(date)
}

export function addWeeks(weekStart: string, amount: number) {
  const date = parseDateOnly(weekStart)
  date.setUTCDate(date.getUTCDate() + amount * 7)
  return formatDateOnly(date)
}

export function isoWeekParts(weekStart: string) {
  const date = parseDateOnly(weekStart)
  date.setUTCDate(date.getUTCDate() + 3)
  const isoYear = date.getUTCFullYear()
  const firstThursday = new Date(Date.UTC(isoYear, 0, 4))
  firstThursday.setUTCDate(firstThursday.getUTCDate() + 3 - ((firstThursday.getUTCDay() + 6) % 7))
  const isoWeek = 1 + Math.round((date.getTime() - firstThursday.getTime()) / (7 * DAY_MS))
  return { isoYear, isoWeek }
}

export function weekLabel(weekStart: string) {
  const { isoYear, isoWeek } = isoWeekParts(weekStart)
  return `${isoYear}年第${isoWeek}周`
}

export function weekRangeLabel(weekStart: string, compact = false) {
  const start = parseDateOnly(weekStart)
  const end = new Date(start.getTime() + 6 * DAY_MS)
  const monthDay = (value: Date) => `${String(value.getUTCMonth() + 1).padStart(2, '0')}${compact ? '/' : '月'}${String(value.getUTCDate()).padStart(2, '0')}${compact ? '' : '日'}`
  return `${monthDay(start)} - ${monthDay(end)}`
}

export function buildWeekWindow(anchor: string, radius = 3) {
  return Array.from({ length: radius * 2 + 1 }, (_, index) => addWeeks(anchor, index - radius))
}
