import { useState } from 'react'
import { useAppStore } from '@/store/AppStore'
import { weekLabel } from '@/lib/isoWeek'
import { useWorkspace } from './useWorkspace'
import { Dialog } from './Dialog'
import { ShiftCard } from './components/schedule/ShiftCard'

export function MobileSchedule({ onClose }: { onClose(): void }) {
  const store = useAppStore()
  const { rows, days } = useWorkspace()
  const [id, setId] = useState(store.employees[0]?.id ?? '')
  const row = rows.find(row => row.employee.id === id)
  return <Dialog title="手机排班预览" onClose={onClose}><div className="mx-auto max-w-xs rounded-[32px] border-[6px] border-slate-900 bg-slate-50 p-4">
    <div className="mx-auto mb-5 h-1 w-14 rounded-full bg-slate-300" /><p className="text-xs font-bold text-blue-600">OPTISHIFT</p><h3 className="my-2 text-xl font-extrabold">我的一周</h3><p className="mb-4 text-xs text-slate-500">{weekLabel(store.activeWeekStart)} · {store.activeSchedule?.status === 'draft' ? '草稿预览' : store.activeSchedule ? '已生效' : '未生成'}</p>
    <select aria-label="预览员工" className="input-base mb-4 w-full" value={id} onChange={event => setId(event.target.value)}>{rows.map(row => <option key={row.employee.id}>{row.employee.id}</option>)}</select>
    <div className="space-y-2">{row?.shifts.map((shift, i) => <div key={shift.id} className="flex items-center gap-3"><div className="w-20 shrink-0 text-xs font-bold">{days[i].dayCn}<p className="font-normal text-slate-400">{days[i].fullDate.slice(5)}</p></div><ShiftCard shift={shift} /></div>)}</div>
    {!store.activeSchedule && <p className="mt-3 text-xs text-slate-500">当前仅展示登记的可用性，请先生成排班。</p>}
  </div></Dialog>
}
