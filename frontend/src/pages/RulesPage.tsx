import { useState } from 'react'
import { Bot, Scale, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { api, apiErrorMessage, type RuleConfig, type StaffingPreview } from '@/api/client'
import { rulePresentation } from '@/lib/presentation'
import { weekLabel } from '@/lib/isoWeek'
import { useAppStore } from '@/store/AppStore'
import { useAgentStore } from '@/store/AgentStore'
import { Dialog } from '@/redesign/Dialog'

export function RulesPage() {
  const store = useAppStore()
  const agent = useAgentStore()
  const { rules } = store
  const config = store.result?.rule_config ?? store.ruleConfig
  const [selected, setSelected] = useState<string | null>(null)
  const rule = rules.find(r => r.id === selected)
  const checks = store.result?.validation.checks.filter(c => c.rule_id === selected) ?? []
  const hard = rules.filter((rule) => rule.category === 'hard')
  const soft = rules.filter((rule) => rule.category === 'soft')
  return (
    <div className="space-y-6">
      <section><p className="eyebrow">后端统一规则源</p><h2 className="mt-1 text-2xl font-extrabold tracking-tight text-ink">规则中心</h2><p className="mt-2 text-sm text-slate-500">规则由后端规则接口统一提供，排班求解与结果校验使用同一套配置。</p></section>
      <StaffingSandbox key={`${store.activeWeekStart}-${store.activeSchedule?.schedule_id ?? 'empty'}`} />
      <section className="panel overflow-hidden"><div className="flex items-center gap-3 border-b border-slate-100 bg-emerald-50/60 p-5"><span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-100 text-emerald-700"><ShieldCheck className="h-5 w-5" /></span><div><h3 className="text-base font-extrabold text-ink">硬约束</h3><p className="text-xs text-slate-500">H01 + R01-R09 · 必须全部满足</p></div></div><RuleGrid config={config} rules={hard} onSelect={setSelected} /></section>
      <section className="panel overflow-hidden"><div className="flex items-center gap-3 border-b border-slate-100 bg-blue-50/60 p-5"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-100 text-blue-700"><Scale className="h-5 w-5" /></span><div><h3 className="text-base font-extrabold text-ink">优化目标</h3><p className="text-xs text-slate-500">S01-S03 · 在硬约束满足后继续优化</p></div></div><RuleGrid config={config} rules={soft} onSelect={setSelected} /></section>
      {rule && <Dialog title={`${rule.id} · ${rulePresentation(rule.id, rule, config).name}`} onClose={() => setSelected(null)}><p className="text-sm leading-7 text-slate-600">{rulePresentation(rule.id, rule, config).description}</p><p className="mt-4 text-sm font-bold">当前周：{checks.length ? checks.every(c => c.passed) ? '满足' : '存在规则提示，请查看排班校验与例外记录' : '尚无校验结果'}</p><div className="mt-5 flex gap-2"><button className="btn-secondary" onClick={() => { setSelected(null); store.setPage('schedule') }}>查看排班校验</button><button className="btn-primary" disabled={agent.isSending} onClick={() => { setSelected(null); void agent.openWithPrompt(`解释 ${rule.id} 规则及其对当前周排班的影响。`) }}><Bot className="h-4 w-4" />问问 AI</button></div></Dialog>}
    </div>
  )
}

function RuleGrid({ rules, onSelect, config }: { config: RuleConfig; rules: ReturnType<typeof useAppStore>['rules']; onSelect(id: string): void }) {
  return <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-3">{rules.map((rule) => { const copy = rulePresentation(rule.id, rule, config); return <button key={rule.id} onClick={() => onSelect(rule.id)} className="rounded-xl border border-slate-200 p-4 text-left transition hover:border-blue-300 hover:bg-blue-50/30"><div className="flex items-center gap-2"><span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs font-black text-slate-700">{rule.id}</span><SlidersHorizontal className="ml-auto h-4 w-4 text-slate-300" /></div><h4 className="mt-3 text-sm font-extrabold text-ink">{copy.name}</h4><p className="mt-2 text-xs leading-5 text-slate-500">{copy.description}</p></button> })}</div>
}

function StaffingSandbox() {
  const store = useAppStore()
  const agent = useAgentStore()
  const config = store.result?.rule_config ?? store.ruleConfig
  const [minimum, setMinimum] = useState(config.weekend_min_staff)
  const [consecutive, setConsecutive] = useState(config.max_consecutive_days)
  const [preview, setPreview] = useState<StaffingPreview | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const busy = pending || store.isRunning || store.isLoadingWeek || agent.isSending || agent.isLoadingConversation || !!store.isSavingEmployee
  const runPreview = async () => {
    setPending(true); setError(''); setPreview(null)
    try { setPreview(await api.schedules.previewStaffing(store.activeWeekStart, minimum, consecutive)) }
    catch (err) { setError(apiErrorMessage(err).message) }
    finally { setPending(false) }
  }
  const generate = async () => {
    if (await store.generate('', store.activeWeekStart, [], minimum, consecutive)) store.setPage('schedule')
  }
  return <section className="rounded-3xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-5 sm:p-6"><div className="flex items-center gap-3"><SlidersHorizontal className="h-6 w-6 text-blue-600" /><div><h3 className="font-extrabold">排班约束沙盒</h3><p className="mt-1 text-xs text-slate-500">{weekLabel(store.activeWeekStart)} · 调整参数，查看真实可行性和人员缺口</p></div></div><div className="mt-5 grid gap-5 md:grid-cols-2"><div><label className="flex justify-between text-sm font-bold" htmlFor="staffing-minimum"><span>周末每班最低人数</span><span className="text-blue-600">{minimum} 人</span></label><input id="staffing-minimum" type="range" min={0} max={Math.max(12, config.weekend_min_staff)} step={1} disabled={busy} className="my-4 w-full accent-blue-600" value={minimum} onChange={e => { setMinimum(Number(e.target.value)); setPreview(null); setError('') }} /><p className="text-xs leading-6 text-slate-500">当前排班要求 {config.weekend_min_staff} 人、最多连续工作 {config.max_consecutive_days} 天。试算不会保存排班。采用参数生成的草稿会保存本周规则，确认和后续重排使用相同配置。</p><label className="mt-3 block text-xs font-bold">连续工作天数上限<select aria-label="连续工作天数上限" disabled={busy} className="input-base mt-2 w-full" value={consecutive} onChange={e => { setConsecutive(Number(e.target.value)); setPreview(null); setError('') }}>{[...new Set([store.ruleConfig.max_consecutive_days, config.max_consecutive_days, 7])].map(value => <option key={value} value={value}>{value} 天{value === store.ruleConfig.max_consecutive_days ? '（标准规则）' : '（调整规则）'}</option>)}</select></label><div className="mt-4 flex flex-wrap gap-2"><button className="btn-secondary" disabled={busy} onClick={() => void runPreview()}>{pending ? '正在试算…' : '运行沙盒试算'}</button><button className="btn-secondary" disabled={busy} onClick={() => { setMinimum(config.weekend_min_staff); setConsecutive(config.max_consecutive_days); setPreview(null); setError('') }}>重置</button><button className="btn-primary" disabled={busy || !!store.draftSchedule || !preview?.strict_feasible} onClick={() => void generate()}>采用参数生成草稿</button></div>{store.draftSchedule && <p className="mt-2 text-xs text-amber-700">本周已有草稿，请先在工作台确认或取消。</p>}</div><div className="rounded-2xl border border-blue-100 bg-white p-4" role="status">{preview ? <><p className={`font-bold ${preview.strict_feasible ? 'text-emerald-700' : 'text-amber-700'}`}>{preview.strict_feasible ? '当前参数存在可行排班' : preview.status === 'infeasible' ? '当前参数无法满足全部约束' : '求解尚未获得可用结果，请重试'}</p><p className="mt-2 text-sm text-slate-500">{preview.strict_feasible ? `试算安排 ${preview.preview_schedule?.assignments.length ?? 0} 个班次，全部通过校验。` : `发现 ${preview.conflicts.length} 项覆盖或约束冲突。`}</p>{preview.conflicts.slice(0, 6).map((c, i) => <p key={i} className="mt-2 text-xs text-amber-700">{c.rule_id} · {c.day} · {c.shift === 'morning' ? '早班' : '晚班'} · 缺 {c.shortage}</p>)}</> : <p className="text-sm leading-7 text-slate-400">调整人数后点击试算。系统同时检查员工可用时间、技能覆盖、工时和跨周休息限制。</p>}{error && <p className="mt-3 text-sm text-red-600">{error}</p>}</div></div></section>
}
