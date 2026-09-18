import { useState } from 'react'
import { Coffee, CreditCard, Package, Save, Shield, UserRound } from 'lucide-react'
import { roleLabel, skillLabel } from '@/lib/presentation'
import { DAYS, type Day, type Employee, type ShiftType } from '@/types'

const dayLabel: Record<Day, string> = { Mon: '一', Tue: '二', Wed: '三', Thu: '四', Fri: '五', Sat: '六', Sun: '日' }

export function EmployeeEditor({ employee, saving, onSave }: { employee: Employee; saving: boolean; onSave(patch: { available_days: Day[]; leave_days: Day[]; preferred_shift: ShiftType | null }): void }) {
  const [available, setAvailable] = useState<Day[]>(employee.available_days)
  const [leave, setLeave] = useState<Day[]>(employee.leave_days)
  const [preference, setPreference] = useState<ShiftType | null>(employee.preferred_shift)
  const toggle = (values: Day[], day: Day, setter: (days: Day[]) => void) => setter(values.includes(day) ? values.filter((value) => value !== day) : [...values, day])
  return (
    <article className="panel overflow-hidden">
      <div className="flex items-center gap-3 border-b border-slate-100 p-4"><span className="grid h-11 w-11 place-items-center rounded-xl bg-teal-50 text-teal-700"><UserRound className="h-5 w-5" /></span><div className="min-w-0 flex-1"><h3 className="text-base font-extrabold text-ink">{employee.id}</h3><p className="text-xs text-slate-400">{roleLabel(employee.role)}</p></div><button onClick={() => onSave({ available_days: available, leave_days: leave, preferred_shift: preference })} disabled={saving} className="btn-primary !px-3 !py-2"><Save className="h-4 w-4" />{saving ? '保存中' : '保存'}</button></div>
      <div className="space-y-5 p-4">
        <div><p className="mb-2 text-[10px] font-bold tracking-wide text-slate-400">已登记技能 · 只读</p><div className="flex flex-wrap gap-2">{employee.skills.map((skill) => <span key={skill} className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-bold text-slate-600">{skill === 'manager' && <Shield className="h-3 w-3 text-blue-600" />}{skill === 'beverage' && <Coffee className="h-3 w-3 text-amber-700" />}{skill === 'cashier' && <CreditCard className="h-3 w-3 text-purple-600" />}{skill === 'inventory' && <Package className="h-3 w-3 text-amber-600" />}{skillLabel(skill)}</span>)}</div></div>
        <DayPicker label="可工作日期" values={available} tone="teal" onToggle={(day) => toggle(available, day, setAvailable)} />
        <DayPicker label="请假日期" values={leave} tone="red" onToggle={(day) => toggle(leave, day, setLeave)} />
        <label className="block"><span className="mb-2 block text-[10px] font-bold tracking-wide text-slate-400">偏好班次</span><select value={preference ?? ''} onChange={(event) => setPreference((event.target.value || null) as ShiftType | null)} className="input-base w-full"><option value="">不限</option><option value="morning">早班 · 09:00–17:00</option><option value="evening">晚班 · 13:00–21:00</option></select></label>
      </div>
    </article>
  )
}

function DayPicker({ label, values, tone, onToggle }: { label: string; values: Day[]; tone: 'teal' | 'red'; onToggle(day: Day): void }) {
  return <div><p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p><div className="grid grid-cols-7 gap-1.5">{DAYS.map((day) => { const selected = values.includes(day); return <button key={day} onClick={() => onToggle(day)} className={`rounded-lg border py-2 text-xs font-extrabold transition ${selected ? tone === 'teal' ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-red-300 bg-red-50 text-red-600' : 'border-slate-200 text-slate-400'}`}>周{dayLabel[day]}</button> })}</div></div>
}
