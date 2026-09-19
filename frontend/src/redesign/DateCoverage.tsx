import { Bot, Plus, ShieldCheck, Users } from 'lucide-react'
import { useAppStore } from '@/store/AppStore'
import { useAgentStore } from '@/store/AgentStore'
import { DAY_LABELS, SHIFT_LABELS, SHIFT_TIMES, rulePresentation } from '@/lib/presentation'
import { SHIFTS, type Day, type ShiftType } from '@/types'
import { useWorkspace } from './useWorkspace'

function useCoverage() {
  const store = useAppStore()
  const { days } = useWorkspace()
  const config = store.result?.rule_config ?? store.ruleConfig
  return days.map(day => {
    const slots = SHIFTS.map(shift => {
      const assignments = store.activeSchedule?.assignments.filter(a => a.day === day.day && a.shift === shift) ?? []
      const employees = store.employees.filter(e => assignments.some(a => a.employee_id === e.id))
      const checks = [
        { id: 'R01', label: '店长', required: config.manager_per_shift, actual: employees.filter(e => e.skills.includes('manager')).length },
        { id: 'R02', label: '饮品', required: config.beverage_per_shift, actual: employees.filter(e => e.skills.includes('beverage')).length },
        { id: 'R03', label: '收银', required: config.cashier_per_shift, actual: employees.filter(e => e.skills.includes('cashier')).length },
        { id: 'R04', label: '人数', required: day.day === 'Sat' || day.day === 'Sun' ? config.weekend_min_staff : config.weekday_min_staff, actual: employees.length },
      ].map(check => {
        const verified = store.result?.validation.coverage?.find(c => c.day === day.day && c.shift === shift && c.rule_id === check.id)
        return verified ? { ...check, required: verified.expected, actual: verified.actual } : check
      })
      const violations = store.result?.validation.violations?.filter(v => v.day === day.day && (!v.shift || v.shift === shift)) ?? []
      return { shift, employees, checks, violations, gap: Math.max(0, ...checks.map(c => c.required - c.actual)) }
    })
    return { ...day, slots, gap: slots.reduce((sum, slot) => sum + slot.gap, 0), issueCount: slots.reduce((sum, slot) => sum + slot.violations.length, 0) }
  })
}

export function ShiftCoverageSummary({ day }: { day: Day }) {
  const store = useAppStore()
  const coverage = useCoverage().find((item) => item.day === day)!
  return (
    <div className="absolute inset-0 pointer-events-none">
      {coverage.slots.map((slot) => (
        <button
          key={slot.shift}
          aria-label={`查看${DAY_LABELS[day]}${SHIFT_LABELS[slot.shift]}详情`}
          onClick={() => store.selectShift({ day, shift: slot.shift })}
          className={`absolute left-0 w-full opacity-[0.005] z-40 pointer-events-auto cursor-pointer overflow-hidden ${
            slot.shift === 'morning' ? 'top-0 h-1/2' : 'bottom-0 h-1/2'
          }`}
        >
          {SHIFT_LABELS[slot.shift]} {slot.employees.length}/{slot.checks[3].required}
          {slot.violations.map((v) => (
            <span key={v.violation_id} className="mt-0.5 block">
              {v.employee_id && `${v.employee_id} · `}
              {v.rule_id} {v.authorized ? '已授权例外' : '规则冲突'}
            </span>
          ))}
        </button>
      ))}
    </div>
  )
}

export function DateCoverage({ selected, onSelect, onAdd, disabled, compact = false, onNavigate }: { selected: Day; onSelect(day: Day): void; onAdd(day: Day, shift: ShiftType): void; disabled: boolean; compact?: boolean; onNavigate?(): void }) {
  const days = useCoverage()
  const store = useAppStore()
  const agent = useAgentStore()
  const active = days.find(d => d.day === selected) ?? days[0]
  return <div className="space-y-4">
    {!compact && <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">{days.map(day => <button key={day.day} onClick={() => onSelect(day.day)} aria-pressed={day.day === selected} className={`rounded-2xl border p-3 text-left transition ${day.day === selected ? 'border-blue-400 bg-blue-50 ring-2 ring-blue-100' : 'border-slate-200 hover:bg-slate-50'}`}><p className="text-xs font-bold">{day.dayCn}</p><p className="mt-1 text-lg font-extrabold">{day.fullDate.slice(5).replace('-', '/')}</p><p className={`mt-3 text-[10px] font-semibold ${day.gap || day.issueCount ? 'text-amber-600' : 'text-emerald-600'}`}>{day.gap ? `缺口 ${day.gap} 人次` : day.issueCount ? `${day.issueCount} 项规则提示` : '覆盖正常'}</p></button>)}</div>}
    <div className="rounded-3xl border border-slate-200 p-4 sm:p-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-extrabold">{active.dayCn} · {active.fullDate}</h3><p className="mt-1 text-xs text-slate-400">早晚班覆盖 · 岗位资格 · 当日人员</p></div><button className="btn-secondary !text-xs" disabled={agent.isSending || store.isRunning || store.isLoadingWeek || !!store.isSavingEmployee} onClick={() => { onNavigate?.(); void agent.openWithPrompt(`分析 ${active.fullDate}（${active.dayCn}）的人员覆盖与规则冲突，并给出调整建议。`, { intent: 'advice', target_week: store.activeWeekStart }) }}><Bot className="h-4 w-4" />AI 调配建议</button></div>
      <div className="grid gap-4 md:grid-cols-2">{active.slots.map(slot => <article key={slot.shift} className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4"><button aria-label={`查看${DAY_LABELS[active.day]}${SHIFT_LABELS[slot.shift]}详情`} onClick={() => { onNavigate?.(); store.selectShift({ day: active.day, shift: slot.shift }) }} className="w-full text-left"><div className="flex items-center justify-between"><h4 className="font-bold text-blue-700">{SHIFT_LABELS[slot.shift]}</h4><span className="text-xs text-slate-400">{SHIFT_TIMES[slot.shift]}</span></div><p className="my-3 text-sm font-bold">{slot.employees.length} / {slot.checks[3].required} 人到岗</p><div className="flex flex-wrap gap-2">{slot.checks.slice(0, 3).map(c => <span key={c.id} className={`rounded-lg px-2 py-1 text-xs ${c.actual < c.required ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-700'}`}>{c.label} {c.actual}/{c.required}</span>)}</div><p className="mt-3 text-xs text-slate-500">{slot.employees.map(e => e.id).join(' · ') || '尚无员工'}</p>{slot.violations.map(v => <p key={v.violation_id} className="mt-2 text-xs text-amber-700">{v.rule_id} {v.authorized ? '已授权例外' : rulePresentation(v.rule_id).name}</p>)}</button>
        <div className="mt-4 flex flex-wrap gap-1.5">{slot.employees.map(employee => <button key={employee.id} onClick={() => { onNavigate?.(); store.selectEmployee(employee.id) }} className="rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-bold text-slate-600 hover:text-blue-600">{employee.id} 档案</button>)}</div><button disabled={disabled} onClick={() => onAdd(active.day, slot.shift)} className="mt-4 inline-flex items-center gap-1 text-xs font-bold text-blue-600 disabled:opacity-40"><Plus className="h-4 w-4" />补充 / 调整班次</button>
      </article>)}</div>
    </div>
  </div>
}

export function CoverageOverview({ onSelectDay }: { onSelectDay(day: Day): void }) {
  const store = useAppStore()
  const days = useCoverage()
  const total = store.activeSchedule?.assignments.length ?? 0
  const gaps = days.reduce((sum, day) => sum + day.gap, 0)
  const workers = new Set(store.activeSchedule?.assignments.map(a => a.employee_id)).size
  return <aside className="space-y-4 rounded-3xl border border-slate-200 bg-[#F8FAFF] p-5"><h3 className="flex items-center gap-2 font-extrabold"><ShieldCheck className="h-5 w-5 text-blue-600" />本周排班概览</h3><div className="grid grid-cols-2 gap-3">{[['已排班次', total], ['计划工时', `${total * 8} h`], ['已排员工', `${workers}/${store.employees.length}`], ['缺口人次', gaps]].map(([label, value]) => <div key={label} className="rounded-2xl border border-slate-100 bg-white p-3"><p className="text-[10px] text-slate-400">{label}</p><p className="mt-1 text-xl font-extrabold">{value}</p></div>)}</div><p className="text-xs font-bold text-slate-500">每日人员覆盖</p><div className="space-y-2">{days.map(day => <button key={day.day} onClick={() => onSelectDay(day.day)} className="flex w-full items-center gap-2 text-xs"><span>{day.dayCn}</span><span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200"><span className={`block h-full rounded-full ${day.gap ? 'bg-amber-400' : 'bg-blue-500'}`} style={{ width: `${Math.min(100, day.slots.reduce((s, slot) => s + slot.employees.length, 0) / Math.max(1, day.slots.reduce((s, slot) => s + slot.checks[3].required, 0)) * 100)}%` }} /></span><span className="w-10 text-right text-slate-500">{day.gap ? `缺 ${day.gap}` : '达标'}</span></button>)}</div><button onClick={() => store.setPage('rules')} className="flex items-center gap-2 text-xs font-bold text-blue-600"><Users className="h-4 w-4" />查看规则与试算</button></aside>
}
