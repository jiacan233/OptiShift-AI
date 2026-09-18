import { ArrowUpRight, CheckCircle2, Coffee, Shield, UsersRound } from 'lucide-react'
import { DAY_LABELS, SHIFT_LABELS, SHIFT_TIMES } from '@/lib/presentation'
import type { Assignment, CoverageCheck, Day, Employee, ShiftType, Violation } from '@/types'

export function ShiftCard({
  day,
  shift,
  assignments,
  employees,
  coverage = [],
  violations = [],
  onClick,
}: {
  day: Day
  shift: ShiftType
  assignments: Assignment[]
  employees: Employee[]
  coverage?: CoverageCheck[]
  violations?: Violation[]
  onClick(): void
}) {
  const people = assignments.flatMap((assignment) => {
    const employee = employees.find((item) => item.id === assignment.employee_id)
    return employee ? [employee] : []
  })
  const healthy = coverage.length === 4 && coverage.every((item) => item.passed) && violations.length === 0

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex h-full min-h-[232px] w-full flex-col rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:-translate-y-0.5 hover:border-teal-300 hover:shadow-md"
      aria-label={`查看${DAY_LABELS[day]}${SHIFT_LABELS[shift]}详情`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${shift === 'morning' ? 'bg-amber-50 text-amber-700' : 'bg-indigo-50 text-indigo-700'}`}>
          {SHIFT_TIMES[shift]}
        </span>
        <ArrowUpRight className="h-4 w-4 text-slate-300 transition group-hover:text-teal-600" />
      </div>

      <div className="mb-3 flex items-center gap-2">
        <UsersRound className="h-4 w-4 text-slate-400" />
        <span className="text-sm font-extrabold text-ink">{people.length} 人</span>
        {healthy && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
      </div>

      <div className="mb-4 min-h-[74px] space-y-1.5">
        {people.slice(0, 6).map((person) => (
          <div key={person.id} className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
            <span className="w-8 text-slate-800">{person.id}</span>
            {person.skills.includes('manager') && <Shield className="h-3.5 w-3.5 fill-blue-100 text-blue-600" aria-label="店长" />}
            {person.skills.includes('beverage') && <span title="饮品制作" className="text-[12px]">🍹</span>}
            {person.skills.includes('cashier') && <Coffee className="h-3.5 w-3.5 text-amber-700" aria-label="收银" />}
          </div>
        ))}
        {people.length > 6 && <p className="text-[10px] font-semibold text-slate-400">另有 {people.length - 6} 人</p>}
        {people.length === 0 && <p className="pt-3 text-center text-xs text-slate-400">暂无人员</p>}
      </div>

      <div className="mt-auto grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-100 pt-2.5 text-[10px]">
        {coverage.map((item) => <Coverage key={item.rule_id} check={item} />)}
      </div>
      {violations.length > 0 && <p className="mt-2 text-[10px] font-bold text-amber-700">⚠ {violations.map((item) => `${item.rule_id} ${item.authorized ? '已授权例外' : '未授权冲突'}`).join(' · ')}</p>}
    </button>
  )
}

function Coverage({ check }: { check: CoverageCheck }) {
  const label = ({ R01: '店长', R02: '饮品', R03: '收银', R04: '总人数' } as Record<string, string>)[check.rule_id]
  return (
    <div className="flex items-center justify-between gap-1">
      <span className="text-slate-400">{label}</span>
      <span className={`font-bold ${check.passed ? 'text-emerald-600' : 'text-red-600'}`}>{check.actual}/{check.expected}{!check.passed && ' ⚠'}</span>
    </div>
  )
}
