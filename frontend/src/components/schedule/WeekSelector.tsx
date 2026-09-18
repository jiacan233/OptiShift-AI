import { ChevronLeft, ChevronRight } from 'lucide-react'
import { addWeeks, isoWeekParts, weekRangeLabel } from '@/lib/isoWeek'
import type { ScheduleWeekSummary } from '@/types'

export function WeekSelector({
  activeWeekStart,
  weeks,
  disabled,
  onSelect,
}: {
  activeWeekStart: string
  weeks: ScheduleWeekSummary[]
  disabled?: boolean
  onSelect(weekStart: string): void
}) {
  const options = weeks.some((item) => item.week_start === activeWeekStart)
    ? weeks
    : [...weeks, { week_start: activeWeekStart }].sort((a, b) => a.week_start.localeCompare(b.week_start))

  return (
    <div className="flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
      <button type="button" disabled={disabled} onClick={() => onSelect(addWeeks(activeWeekStart, -1))} className="grid h-9 w-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40" aria-label="上一周"><ChevronLeft className="h-4 w-4" /></button>
      <select value={activeWeekStart} disabled={disabled} onChange={(event) => onSelect(event.target.value)} className="min-w-0 max-w-[220px] rounded-lg border-0 bg-transparent px-2 py-1.5 text-xs font-bold text-slate-700 outline-none disabled:opacity-50" aria-label="选择排班周次">
        {options.map((item) => {
          const { isoWeek } = isoWeekParts(item.week_start)
          const state = item.version ? `v${item.version}` : '未生成'
          const current = item.week_start === activeWeekStart ? ' · 当前' : ''
          return <option key={item.week_start} value={item.week_start}>第{isoWeek}周 · {weekRangeLabel(item.week_start, true)} · {state}{current}</option>
        })}
      </select>
      <button type="button" disabled={disabled} onClick={() => onSelect(addWeeks(activeWeekStart, 1))} className="grid h-9 w-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-40" aria-label="下一周"><ChevronRight className="h-4 w-4" /></button>
    </div>
  )
}
