import { Sunrise, Sunset } from 'lucide-react'
import { DAY_LABELS, SHIFT_LABELS, SHIFT_TIMES } from '@/lib/presentation'
import { DAYS, SHIFTS, type Day, type Employee, type Schedule, type ShiftType, type ValidationResult } from '@/types'
import { ShiftCard } from './ShiftCard'

export function ScheduleGrid({
  schedule,
  employees,
  validation,
  onSelectShift,
}: {
  schedule: Schedule
  employees: Employee[]
  validation?: ValidationResult
  onSelectShift(day: Day, shift: ShiftType): void
}) {
  return (
    <div className="soft-scrollbar overflow-x-auto pb-2">
      <div className="min-w-[1170px]">
        <div className="grid grid-cols-[92px_repeat(7,minmax(142px,1fr))] gap-2">
          <div />
          {DAYS.map((day) => (
            <div key={day} className="rounded-xl bg-slate-50 px-3 py-2 text-center">
              <span className="block text-[10px] font-bold tracking-[0.14em] text-slate-400">星期</span>
              <span className="block text-sm font-extrabold text-slate-700">{DAY_LABELS[day]}</span>
            </div>
          ))}

          {SHIFTS.map((shift) => (
            <ShiftRow key={shift} shift={shift} schedule={schedule} employees={employees} validation={validation} onSelectShift={onSelectShift} />
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
  validation,
  onSelectShift,
}: {
  shift: ShiftType
  schedule: Schedule
  employees: Employee[]
  validation?: ValidationResult
  onSelectShift(day: Day, shift: ShiftType): void
}) {
  const Icon = shift === 'morning' ? Sunrise : Sunset
  return (
    <>
      <div className="flex flex-col items-center justify-center rounded-xl bg-slate-50 p-2 text-center">
        <Icon className={`mb-2 h-5 w-5 ${shift === 'morning' ? 'text-amber-500' : 'text-indigo-500'}`} />
        <span className="text-xs font-extrabold text-slate-700">{SHIFT_LABELS[shift]}</span>
        <span className="mt-1 text-[9px] tracking-wider text-slate-400">{SHIFT_TIMES[shift]}</span>
      </div>
      {DAYS.map((day) => (
        <ShiftCard
          key={`${day}-${shift}`}
          day={day}
          shift={shift}
          assignments={schedule.assignments.filter((item) => item.day === day && item.shift === shift)}
          employees={employees}
          coverage={validation?.coverage?.filter((item) => item.day === day && item.shift === shift)}
          violations={validation?.violations?.filter((item) => item.day === day && item.shift === shift)}
          onClick={() => onSelectShift(day, shift)}
        />
      ))}
    </>
  )
}
