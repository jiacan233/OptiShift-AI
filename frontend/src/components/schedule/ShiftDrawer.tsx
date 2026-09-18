import { CheckCircle2, Clock3, Coffee, Shield, X } from 'lucide-react'
import { DAY_LABELS, roleLabel, SHIFT_LABELS, SHIFT_TIMES, skillLabel } from '@/lib/presentation'
import type { CoverageCheck, Day, Employee, Schedule, ShiftType, ValidationResult } from '@/types'
import { ViolationDetails } from './ViolationDetails'

export function ShiftDrawer({
  selection,
  schedule,
  employees,
  validation,
  onClose,
}: {
  selection: { day: Day; shift: ShiftType } | null
  schedule: Schedule | null
  employees: Employee[]
  validation?: ValidationResult
  onClose(): void
}) {
  if (!selection || !schedule) return null
  const assignedIds = schedule.assignments
    .filter((item) => item.day === selection.day && item.shift === selection.shift)
    .map((item) => item.employee_id)
  const people = assignedIds.flatMap((id) => {
    const employee = employees.find((item) => item.id === id)
    return employee ? [employee] : []
  })
  const coverage = validation?.coverage?.filter((item) => item.day === selection.day && item.shift === selection.shift) ?? []
  const violations = validation?.violations?.filter((item) => item.day === selection.day && item.shift === selection.shift) ?? []

  return (
    <>
      <button className="fixed inset-0 z-40 cursor-default bg-ink/30 backdrop-blur-sm" onClick={onClose} aria-label="关闭班次详情" />
      <aside className="fixed inset-y-0 right-0 z-50 w-full max-w-md overflow-y-auto bg-white p-5 shadow-drawer sm:p-7" aria-label="班次详情">
        <div className="mb-8 flex items-start justify-between">
          <div>
            <p className="eyebrow">班次详情</p>
            <h2 className="mt-2 text-2xl font-extrabold tracking-tight text-ink">
              {DAY_LABELS[selection.day]} · {SHIFT_LABELS[selection.shift]}
            </h2>
            <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
              <Clock3 className="h-4 w-4" />
              {SHIFT_TIMES[selection.shift]}
            </div>
          </div>
          <button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500 hover:bg-slate-50" aria-label="关闭"><X className="h-5 w-5" /></button>
        </div>

        <section>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-extrabold text-ink">当班员工</h3>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{people.length} 人</span>
          </div>
          <div className="space-y-2">
            {people.map((employee) => (
              <div key={employee.id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3">
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-slate-100 text-xs font-extrabold text-slate-700">{employee.id}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold text-slate-800">{roleLabel(employee.role)}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {employee.skills.map((skill) => <span key={skill} className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">{skillLabel(skill)}</span>)}
                  </div>
                </div>
                <div className="flex gap-1 text-slate-400">
                  {employee.skills.includes('manager') && <Shield className="h-4 w-4 text-blue-600" />}
                  {employee.skills.includes('beverage') && <span>🍹</span>}
                  {employee.skills.includes('cashier') && <Coffee className="h-4 w-4 text-amber-700" />}
                </div>
              </div>
            ))}
            {people.length === 0 && <div className="rounded-xl border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400">该班次暂无人员</div>}
          </div>
        </section>

        <section className="mt-8">
          <h3 className="mb-3 text-sm font-extrabold text-ink">覆盖检查</h3>
          <div className="overflow-hidden rounded-xl border border-slate-200">
            {coverage.map((item) => <DrawerRule key={item.rule_id} check={item} />)}
          </div>
          <p className="my-3 text-[11px] leading-5 text-slate-400">覆盖检查和授权状态来自后端独立规则校验。</p>
          <ViolationDetails violations={violations} />
        </section>
      </aside>
    </>
  )
}

function DrawerRule({ check }: { check: CoverageCheck }) {
  const { rule_id: id, actual: current, expected: required, passed } = check
  const label = ({ R01: '店长覆盖', R02: '饮品制作覆盖', R03: '收银覆盖', R04: '最低在岗人数' } as Record<string, string>)[id]
  return (
    <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
      {passed ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <X className="h-5 w-5 text-red-500" />}
      <div className="flex-1">
        <p className="text-sm font-bold text-slate-700">{id} {label}</p>
        <p className="text-[11px] text-slate-400">{current} / ≥{required}</p>
      </div>
      <span className={`text-xs font-extrabold ${passed ? 'text-emerald-600' : 'text-red-600'}`}>{passed ? '已满足' : '有缺口'}</span>
    </div>
  )
}
