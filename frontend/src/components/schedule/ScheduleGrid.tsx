import { Sunrise, Sunset } from 'lucide-react'
import { DAYS, SHIFTS, type Day, type Employee, type Schedule, type ShiftType } from '@/types'
import { ShiftCard } from './ShiftCard'

const dayNames: Record<Day, { en: string; zh: string }> = {
  Mon: { en: 'MON', zh: '周一' }, Tue: { en: 'TUE', zh: '周二' }, Wed: { en: 'WED', zh: '周三' },
  Thu: { en: 'THU', zh: '周四' }, Fri: { en: 'FRI', zh: '周五' }, Sat: { en: 'SAT', zh: '周六' }, Sun: { en: 'SUN', zh: '周日' },
}

export function ScheduleGrid({
  schedule,
  employees,
  onSelectShift,
}: {
  schedule: Schedule
  employees: Employee[]
  onSelectShift(day: Day, shift: ShiftType): void
}) {
  return (
    <div className="soft-scrollbar overflow-x-auto pb-2">
      <div className="min-w-[1170px]">
        <div className="grid grid-cols-[92px_repeat(7,minmax(142px,1fr))] gap-2">
          <div />
          {DAYS.map((day) => (
            <div key={day} className="rounded-xl bg-slate-50 px-3 py-2 text-center">
              <span className="block text-[10px] font-bold tracking-[0.14em] text-slate-400">{dayNames[day].en}</span>
              <span className="block text-sm font-extrabold text-slate-700">{dayNames[day].zh}</span>
            </div>
          ))}

          {SHIFTS.map((shift) => (
            <ShiftRow key={shift} shift={shift} schedule={schedule} employees={employees} onSelectShift={onSelectShift} />
          ))}
        </div>
      </div>
    </div>
  )
}

function ShiftRow({
  shift,
  schedule,
  employees,
  onSelectShift,
}: {
  shift: ShiftType
  schedule: Schedule
  employees: Employee[]
  onSelectShift(day: Day, shift: ShiftType): void
}) {
  const Icon = shift === 'morning' ? Sunrise : Sunset
  return (
    <>
      <div className="flex flex-col items-center justify-center rounded-xl bg-slate-50 p-2 text-center">
        <Icon className={`mb-2 h-5 w-5 ${shift === 'morning' ? 'text-amber-500' : 'text-indigo-500'}`} />
        <span className="text-xs font-extrabold text-slate-700">{shift === 'morning' ? '早班' : '晚班'}</span>
        <span className="mt-1 text-[9px] uppercase tracking-wider text-slate-400">{shift}</span>
      </div>
      {DAYS.map((day) => (
        <ShiftCard
          key={`${day}-${shift}`}
          day={day}
          shift={shift}
          assignments={schedule.assignments.filter((item) => item.day === day && item.shift === shift)}
          employees={employees}
          onClick={() => onSelectShift(day, shift)}
        />
      ))}
    </>
  )
}
