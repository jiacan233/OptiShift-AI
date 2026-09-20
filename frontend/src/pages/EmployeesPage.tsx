import { useState } from 'react'
import { Search, Users, ShieldCheck, Clock, CalendarOff } from 'lucide-react'
import { useAppStore } from '@/store/AppStore'
import { useWorkspace, SKILLS } from '@/redesign/useWorkspace'
import { EmployeeTable } from '@/redesign/components/employees/EmployeeTable'
import { SkillsMatrix } from '@/redesign/components/employees/SkillsMatrix'

export function EmployeesPage() {
  const store = useAppStore()
  const { employees, days } = useWorkspace()
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('all')
  const [skill, setSkill] = useState('all')
  const [tab, setTab] = useState('roster')
  const filtered = employees.filter(e => (!query || `${e.id} ${e.role}`.toLowerCase().includes(query.toLowerCase())) && (role === 'all' || e.role === role) && (skill === 'all' || e.skills.some(s => s === skill)))
  const reset = () => { setQuery(''); setRole('all'); setSkill('all') }
  const select = (employee: { id: string }) => store.selectEmployee(employee.id)
  const summaries = [
    { icon: Users, label: '员工总数', value: employees.length },
    { icon: ShieldCheck, label: '具备店长资格', value: employees.filter(e => e.skills.includes('店长值守')).length },
    { icon: Clock, label: '当前周排班工时', value: `${employees.reduce((sum, e) => sum + e.currentHours, 0)} h` },
    { icon: CalendarOff, label: '登记请假人数', value: employees.filter(e => e.leaveDays.length).length },
  ]
  return <div className="space-y-5 animate-fade-in">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-extrabold">员工档案与技能中心</h2><p className="mt-1 text-xs text-slate-400">所有视图使用同一份员工档案 · 点击员工查看排班与编辑可用时间</p></div></div>
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">{summaries.map(({ icon: Icon, label, value }) => <div key={label} className="flex items-center gap-3 rounded-2xl border border-slate-200/80 p-4"><span className="rounded-xl bg-blue-50 p-2 text-blue-600"><Icon className="h-5 w-5" /></span><div><p className="text-[11px] text-slate-400">{label}</p><p className="mt-1 text-xl font-extrabold">{value}</p></div></div>)}</div>
    <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-slate-50 p-3"><div className="relative"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" /><input className="input-base !pl-9" aria-label="搜索员工" placeholder="搜索工号 / 岗位" value={query} onChange={e => setQuery(e.target.value)} /></div><select aria-label="员工岗位筛选" className="input-base" value={role} onChange={e => setRole(e.target.value)}><option value="all">全部岗位</option>{[...new Set(employees.map(e => e.role))].map(role => <option key={role}>{role}</option>)}</select><select aria-label="员工技能筛选" className="input-base" value={skill} onChange={e => setSkill(e.target.value)}><option value="all">全部技能</option>{Object.values(SKILLS).map(skill => <option key={skill}>{skill}</option>)}</select><button className="text-xs font-bold text-blue-600" onClick={reset}>重置筛选</button></div>
    <div className="flex flex-wrap gap-2">{[['roster', '员工列表'], ['skills', '技能矩阵'], ['availability', '可用性矩阵']].map(([id, label]) => <button key={id} onClick={() => setTab(id)} aria-pressed={tab === id} className={`rounded-xl px-4 py-2 text-sm font-bold ${tab === id ? 'bg-blue-600 text-white' : 'bg-slate-50 text-slate-500'}`}>{label}</button>)}<span className="ml-auto self-center text-xs text-slate-400">{filtered.length} / {employees.length} 名员工</span></div>
    {tab === 'roster' && <EmployeeTable employees={filtered} onSelectEmployee={select} onClearFilters={reset} />}
    {tab === 'skills' && <SkillsMatrix employees={filtered} allEmployees={employees} availableSkills={Object.values(SKILLS)} onSelectEmployee={select} onClearFilters={reset} activeSkillFilter={skill} onSkillFilterChange={setSkill} />}
    {tab === 'availability' && <div className="overflow-auto rounded-3xl border border-slate-200"><table className="w-full min-w-[740px] text-center text-xs"><thead className="bg-slate-50"><tr><th className="p-4 text-left">员工</th>{days.map(day => <th key={day.day} className="p-3">{day.dayCn}<p className="font-normal text-slate-400">{day.fullDate.slice(5)}</p></th>)}</tr></thead><tbody>{filtered.map(employee => <tr key={employee.id} className="border-t border-slate-100"><td className="p-4 text-left"><button onClick={() => select(employee)} className="font-bold text-blue-600">{employee.id}</button></td>{days.map(day => { const leave = employee.leaveDays.includes(day.day); const available = employee.availableDays.includes(day.day); return <td key={day.day} className="p-2"><span className={`block rounded-lg px-2 py-2 ${leave ? 'bg-rose-50 text-rose-600' : available ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>{leave ? '请假' : available ? '可排班' : '不可用'}</span></td> })}</tr>)}</tbody></table>{!filtered.length && <p className="p-8 text-center text-sm text-slate-400">没有匹配的员工</p>}</div>}
  </div>
}
