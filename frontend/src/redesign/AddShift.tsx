import { useState, type FormEvent } from 'react'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import { SHIFT_LABELS, SHIFT_TIMES, roleLabel } from '@/lib/presentation'
import { SHIFTS, type Day, type ShiftType } from '@/types'
import { Dialog } from './Dialog'
import { useWorkspace } from './useWorkspace'

export function AddShift({ initialDay, initialShift, initialEmployee, onClose }: { initialDay: Day; initialShift: ShiftType; initialEmployee?: string; onClose(): void }) {
  const store = useAppStore()
  const agent = useAgentStore()
  const busy = store.isRunning || store.isLoadingWeek || agent.isSending || agent.isLoadingConversation || !!store.isSavingEmployee
  const { days } = useWorkspace()
  const [day, setDay] = useState(initialDay)
  const [shift, setShift] = useState(initialShift)
  const [employeeId, setEmployeeId] = useState(initialEmployee ?? '')
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const selected = store.employees.find(e => e.id === employeeId)
  const unavailable = selected && (!selected.available_days.includes(day) || selected.leave_days.includes(day))
  const duplicate = store.activeSchedule?.assignments.some(a => a.employee_id === employeeId && a.day === day && a.shift === shift)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || saving || !selected || unavailable || duplicate || store.draftSchedule) return
    setSaving(true)
    const changes = [{ employee_id: employeeId, type: 'assign' as const, day, shift }]
    const success = store.confirmedSchedule ? await store.replan('', changes) : await store.generate('', store.activeWeekStart, changes)
    setSaving(false)
    setFailed(!success)
    if (success) onClose()
  }
  return <Dialog title="新增班次" onClose={() => { if (!saving) onClose() }}><form onSubmit={e => void submit(e)} className="space-y-4"><p className="text-xs leading-5 text-slate-500">指定员工和班次后，系统会重新计算本周排班，尽量保留现有安排。结果需确认后正式生效。</p>
    <label className="block text-sm font-bold">日期<select className="input-base mt-2 w-full" value={day} onChange={e => setDay(e.target.value as Day)}>{days.map(d => <option key={d.day} value={d.day}>{d.fullDate} · {d.dayCn}</option>)}</select></label>
    <label className="block text-sm font-bold">班次<select className="input-base mt-2 w-full" value={shift} onChange={e => setShift(e.target.value as ShiftType)}>{SHIFTS.map(s => <option key={s} value={s}>{SHIFT_LABELS[s]} · {SHIFT_TIMES[s]}</option>)}</select></label>
    <label className="block text-sm font-bold">员工<select required className="input-base mt-2 w-full" value={employeeId} onChange={e => setEmployeeId(e.target.value)}><option value="">请选择员工</option>{store.employees.map(e => <option key={e.id} value={e.id}>{e.id} · {roleLabel(e.role)}{e.leave_days.includes(day) ? ' · 请假' : !e.available_days.includes(day) ? ' · 不可用' : ''}</option>)}</select></label>
    {unavailable && <p role="alert" className="text-sm text-amber-700">该员工当天请假或不可用，请选择其他员工。</p>}{duplicate && <p className="text-sm text-amber-700">该员工已经在此班次。</p>}{store.draftSchedule && <p className="text-sm text-amber-700">请先确认或取消当前草稿。</p>}
    {failed && <p role="alert" className="text-sm text-red-600">{store.error?.message ?? '无法满足本次安排，关闭窗口可查看工作台的冲突诊断。'}</p>}
    <button type="submit" className="btn-primary w-full" disabled={busy || saving || !selected || unavailable || duplicate || !!store.draftSchedule}>{saving ? '正在求解并校验…' : '生成调整草稿'}</button>
  </form></Dialog>
}
