import { ArrowUpRight, CheckCircle2, Coffee, Shield, UsersRound } from 'lucide-react'
import type { Assignment, Day, Employee, ShiftType } from '@/types'

const requirements = { manager: 1, beverage: 2, cashier: 1 }

export function ShiftCard({
  day,
  shift,
  assignments,
  employees,
  onClick,
}: {
  day: Day
  shift: ShiftType
  assignments: Assignment[]
  employees: Employee[]
  onClick(): void
}) {
  const people = assignments.flatMap((assignment) => {
    const employee = employees.find((item) => item.id === assignment.employee_id)
    return employee ? [employee] : []
  })
  const manager = people.filter((person) => person.skills.includes('manager')).length
  const beverage = people.filter((person) => person.skills.includes('beverage')).length
  const cashier = people.filter((person) => person.skills.includes('cashier')).length
  const minimum = day === 'Sat' || day === 'Sun' ? 6 : 4
  const healthy = manager >= 1 && beverage >= 2 && cashier >= 1 && people.length >= minimum

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex h-full min-h-[232px] w-full flex-col rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:-translate-y-0.5 hover:border-teal-300 hover:shadow-md"
      aria-label={`查看 ${day} ${shift} 班次详情`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${shift === 'morning' ? 'bg-amber-50 text-amber-700' : 'bg-indigo-50 text-indigo-700'}`}>
          {shift === 'morning' ? '09:00–17:00' : '13:00–21:00'}
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
        <Coverage label="Manager" current={manager} required={requirements.manager} />
        <Coverage label="Beverage" current={beverage} required={requirements.beverage} />
        <Coverage label="Cashier" current={cashier} required={requirements.cashier} />
        <Coverage label="Staff" current={people.length} required={minimum} />
      </div>
    </button>
  )
}

function Coverage({ label, current, required }: { label: string; current: number; required: number }) {
  const passed = current >= required
  return (
    <div className="flex items-center justify-between gap-1">
      <span className="text-slate-400">{label}</span>
      <span className={`font-bold ${passed ? 'text-emerald-600' : 'text-red-600'}`}>{current}/{required}</span>
    </div>
  )
}
