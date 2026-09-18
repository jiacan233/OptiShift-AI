import { useState, type FormEvent } from 'react'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import { DAYS, type Employee } from '@/types'
import { Dialog } from './Dialog'
import { SKILLS } from './useWorkspace'

export function AddEmployee({ onClose }: { onClose(): void }) {
  const store = useAppStore()
  const agent = useAgentStore()
  const busy = store.isRunning || store.isLoadingWeek || agent.isSending || agent.isLoadingConversation || !!store.isSavingEmployee
  const [employee, setEmployee] = useState<Employee>({ id: '', role: 'full_time', skills: [], available_days: [...DAYS], leave_days: [], preferred_shift: null })
  const [saving, setSaving] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || saving) return
    setSaving(true)
    const created = await store.createEmployee({ ...employee, id: employee.id.trim() })
    setSaving(false)
    if (created) onClose()
  }
  return <Dialog title="添加员工" onClose={() => { if (!saving) onClose() }}><form className="space-y-4" onSubmit={event => void submit(event)}>
    <label className="block text-sm font-bold">员工编号<input className="input-base mt-2 w-full" required maxLength={32} pattern="[A-Za-z0-9_-]+" placeholder="例如 E21" value={employee.id} onChange={e => setEmployee({ ...employee, id: e.target.value })} /></label>
    <label className="block text-sm font-bold">岗位<select className="input-base mt-2 w-full" value={employee.role} onChange={e => setEmployee({ ...employee, role: e.target.value })}><option value="manager">店长</option><option value="full_time">全职员工</option><option value="part_time">兼职员工</option></select></label>
    <fieldset><legend className="mb-2 text-sm font-bold">登记认证技能</legend><p className="mb-3 text-xs text-slate-400">按实际资质登记；岗位名称不会自动赋予技能。</p><div className="grid grid-cols-2 gap-2">{Object.entries(SKILLS).map(([id, name]) => <label key={id} className="flex items-center gap-2 rounded-xl border p-3 text-sm"><input type="checkbox" checked={employee.skills.includes(id)} onChange={e => setEmployee({ ...employee, skills: e.target.checked ? [...employee.skills, id] : employee.skills.filter(skill => skill !== id) })} />{name}</label>)}</div></fieldset>
    <p className="text-xs leading-5 text-slate-500">添加后可在员工档案设置可用时间、请假与早晚班偏好。初始为全周可用、无请假、无偏好。</p>
    {store.error && <p role="alert" className="text-sm text-red-600">{store.error.message}</p>}
    <button disabled={busy || saving} className="btn-primary w-full" type="submit">{saving ? '正在保存…' : '保存员工档案'}</button>
  </form></Dialog>
}
