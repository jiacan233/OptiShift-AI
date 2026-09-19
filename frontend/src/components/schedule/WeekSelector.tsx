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
    <div className="flex items-center gap-1.5 rounded-2xl border border-slate-200/80 bg-white px-1.5 py-1 shadow-xs">
      <button type="button" disabled={disabled} onClick={() => onSelect(addWeeks(activeWeekStart, -1))} className="w-7 h-7 rounded-xl flex items-center justify-center text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition disabled:opacity-40" aria-label="上一周"><ChevronLeft className="w-4 h-4" /></button>
      <select value={activeWeekStart} disabled={disabled} onChange={(event) => onSelect(event.target.value)} className="min-w-0 max-w-[240px] rounded-xl border-0 bg-transparent px-2 py-1 text-xs md:text-sm font-semibold text-slate-800 outline-none disabled:opacity-50 tracking-tight cursor-pointer" aria-label="选择排班周次">
        {options.map((item) => {
          const { isoWeek } = isoWeekParts(item.week_start)
          const state = item.version ? `v${item.version}` : '未生成'
          const current = item.week_start === activeWeekStart ? ' · 当前' : ''
          return <option key={item.week_start} value={item.week_start}>第{isoWeek}周 · {weekRangeLabel(item.week_start, true)} · {state}{current}</option>
        })}
      </select>
      <button type="button" disabled={disabled} onClick={() => onSelect(addWeeks(activeWeekStart, 1))} className="w-7 h-7 rounded-xl flex items-center justify-center text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition disabled:opacity-40" aria-label="下一周"><ChevronRight className="w-4 h-4" /></button>
    </div>
  )
}
