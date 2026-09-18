import { useAppStore } from '@/store/AppStore'
import { useAgentStore } from '@/store/AgentStore'
import { weekLabel, weekRangeLabel } from '@/lib/isoWeek'
import { EmployeeEditor } from './EmployeeEditor'
import { Dialog } from './Dialog'
import { useWorkspace } from './useWorkspace'
import { ShiftCard } from './components/schedule/ShiftCard'

export function EmployeeDetail() {
  const store = useAppStore()
  const agent = useAgentStore()
  const { rows, days } = useWorkspace()
  const employee = store.employees.find(employee => employee.id === store.selectedEmployeeId)
  const row = rows.find(row => row.employee.id === employee?.id)
  if (!employee) return null
  return <Dialog title={`${employee.id} · 员工档案`} onClose={() => store.selectEmployee(null)} wide>
    <p className="mb-4 text-xs text-slate-500">{weekLabel(store.activeWeekStart)} · {weekRangeLabel(store.activeWeekStart)} · {store.activeSchedule?.status === 'draft' ? '草稿排班' : store.activeSchedule ? '正式排班' : '尚未排班'}</p>
    <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-7">{row?.shifts.map((shift, i) => <div key={shift.id}><p className="mb-1 text-center text-xs text-slate-400">{days[i].dayCn}</p><ShiftCard shift={shift} /></div>)}</div>
    <EmployeeEditor key={`${employee.id}-${employee.available_days.join('')}-${employee.leave_days.join('')}-${employee.preferred_shift}`} employee={employee} saving={!!store.isSavingEmployee || store.isRunning || store.isLoadingWeek || agent.isSending || agent.isLoadingConversation} onSave={patch => void store.updateEmployee(employee.id, patch)} />
    <p className="mt-3 text-xs leading-5 text-slate-400">可用时间与请假是员工档案中的每周设置。单周临时请假请在 AI 助手中指定日期；修改资料后会重新校验当前排班。</p>
    {store.error && <p role="alert" className="mt-3 text-sm text-red-600">{store.error.message}</p>}
    {store.notice && <p role="status" className="mt-3 text-sm text-emerald-700">{store.notice}</p>}
  </Dialog>
}
