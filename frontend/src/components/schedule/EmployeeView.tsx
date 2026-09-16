import { CalendarDays, Gauge, Heart, UserRound } from 'lucide-react'
import { DAYS, type Day, type Employee, type Schedule } from '@/types'

const dayName: Record<Day, string> = { Mon: '周一', Tue: '周二', Wed: '周三', Thu: '周四', Fri: '周五', Sat: '周六', Sun: '周日' }

export function EmployeeView({ schedule, employees }: { schedule: Schedule; employees: Employee[] }) {
  const assignedEmployees = employees.filter((employee) => schedule.assignments.some((item) => item.employee_id === employee.id))
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {assignedEmployees.map((employee) => {
        const assignments = schedule.assignments.filter((item) => item.employee_id === employee.id)
        const matched = assignments.filter((item) => employee.preferred_shift === item.shift).length
        const maxConsecutive = longestRun(assignments.map((item) => item.day))
        return (
          <article key={employee.id} className="panel overflow-hidden">
            <div className="flex items-center gap-3 border-b border-slate-100 p-4">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal-50 text-teal-700"><UserRound className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <p className="text-base font-extrabold text-ink">{employee.id}</p>
                <p className="text-[11px] capitalize text-slate-400">{employee.role} · 偏好 {employee.preferred_shift ?? '不限'}</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{assignments.length}/5 班</span>
            </div>
            <div className="grid grid-cols-7 gap-1 p-4">
              {DAYS.map((day) => {
                const assignment = assignments.find((item) => item.day === day)
                const leave = employee.leave_days.includes(day)
                return (
                  <div key={day} className="text-center">
                    <p className="mb-1.5 text-[9px] font-bold text-slate-400">{dayName[day]}</p>
                    <div className={`grid h-12 place-items-center rounded-lg border text-[9px] font-bold ${assignment ? assignment.shift === 'morning' ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-indigo-200 bg-indigo-50 text-indigo-700' : leave ? 'border-red-100 bg-red-50 text-red-500' : 'border-slate-100 bg-slate-50 text-slate-400'}`}>
                      {assignment ? (assignment.shift === 'morning' ? '早班' : '晚班') : leave ? '请假' : '休息'}
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="grid grid-cols-3 border-t border-slate-100 bg-slate-50/70">
              <Metric icon={CalendarDays} label="已排班" value={`${assignments.length}/5`} />
              <Metric icon={Heart} label="偏好匹配" value={assignments.length ? `${matched}/${assignments.length}` : '—'} />
              <Metric icon={Gauge} label="最长连班" value={`${maxConsecutive} 天`} />
            </div>
          </article>
        )
      })}
    </div>
  )
}

function Metric({ icon: Icon, label, value }: { icon: typeof CalendarDays; label: string; value: string }) {
  return (
    <div className="border-r border-slate-100 px-2 py-3 text-center last:border-r-0">
      <Icon className="mx-auto mb-1 h-3.5 w-3.5 text-slate-400" />
      <p className="text-xs font-extrabold text-slate-700">{value}</p>
      <p className="text-[9px] text-slate-400">{label}</p>
    </div>
  )
}

function longestRun(days: Day[]) {
  const indexes = days.map((day) => DAYS.indexOf(day)).sort((a, b) => a - b)
  let max = 0
  let current = 0
  let previous = -2
  indexes.forEach((index) => {
    current = index === previous + 1 ? current + 1 : 1
    previous = index
    max = Math.max(max, current)
  })
  return max
}
