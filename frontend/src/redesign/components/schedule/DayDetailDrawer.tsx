import type { DayCoverage, ShiftCoverage, Employee } from '../../types/schedule'
import { Dialog } from '../../Dialog'
import { AssignedEmployeeChip } from './AssignedEmployeeChip'

interface DayDetailDrawerProps {
  day: DayCoverage | null
  isOpen: boolean
  onClose(): void
  onAddShiftForSlot(date: string, shift: 'morning' | 'evening'): void
  onAskAiForDay(day: DayCoverage, shift?: ShiftCoverage): void
  onViewConflicts(): void
  onSelectEmployee?(employee: Employee): void
  addShiftDisabled: boolean
  aiDisabled: boolean
}

export function DayDetailDrawer({ day, isOpen, onClose, onAddShiftForSlot, onAskAiForDay, onViewConflicts, onSelectEmployee, addShiftDisabled, aiDisabled }: DayDetailDrawerProps) {
  if (!isOpen || !day) return null
  return <Dialog title={`${day.fullDate} ${day.dayCn} · 班次覆盖详情`} onClose={onClose} wide>
    <div className="space-y-4">
      <p className="text-sm text-slate-600">已排 {day.totalEmployees} 人 · {day.totalHours} 小时 · {day.statusText}</p>
      {day.shifts.map(shift => <section key={shift.shiftType} className="rounded-2xl border border-slate-200 p-4 space-y-3">
        <h3 className="font-bold text-slate-800">{shift.shiftName} · {shift.timeRange}</h3>
        <p className="text-sm text-slate-600">{shift.assignedCount} / {shift.requirementText ?? shift.requiredCount} 人；店长 {shift.managerCount}/{shift.managerRequired} · 饮品 {shift.baristaCount}/{shift.beverageRequired} · 收银 {shift.cashierCount}/{shift.cashierRequired}</p>
        <div className="flex flex-wrap gap-2">{shift.employees.map(employee => <AssignedEmployeeChip key={employee.id} employee={employee} onClick={person => onSelectEmployee?.(person)} />)}</div>
        {shift.ruleIssues.map((issue, index) => <p key={`${issue.ruleId}-${index}`} className="text-xs text-amber-700">{issue.ruleId} · {issue.message}</p>)}
        <div className="flex gap-2">
          <button className="btn-secondary" disabled={addShiftDisabled} onClick={() => onAddShiftForSlot(day.fullDate, shift.shiftType === 'morning' ? 'morning' : 'evening')}>补充 / 调整班次</button>
          <button className="btn-primary" disabled={aiDisabled} onClick={() => onAskAiForDay(day, shift)}>AI 调配建议</button>
        </div>
      </section>)}
      <button className="btn-secondary" onClick={onViewConflicts}>查看日期覆盖</button>
    </div>
  </Dialog>
}
