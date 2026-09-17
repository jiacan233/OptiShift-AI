import { Scale, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { rulePresentation } from '@/lib/presentation'
import { useAppStore } from '@/store/AppStore'

export function RulesPage() {
  const { rules } = useAppStore()
  const hard = rules.filter((rule) => rule.category === 'hard')
  const soft = rules.filter((rule) => rule.category === 'soft')
  return (
    <div className="space-y-6">
      <section><p className="eyebrow">后端统一规则源</p><h2 className="mt-1 text-2xl font-extrabold tracking-tight text-ink">规则中心</h2><p className="mt-2 text-sm text-slate-500">规则由后端规则接口统一提供，排班求解与结果校验使用同一套配置。</p></section>
      <section className="panel overflow-hidden"><div className="flex items-center gap-3 border-b border-slate-100 bg-emerald-50/60 p-5"><span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-100 text-emerald-700"><ShieldCheck className="h-5 w-5" /></span><div><h3 className="text-base font-extrabold text-ink">硬约束</h3><p className="text-xs text-slate-500">H01 + R01-R09 · 必须全部满足</p></div></div><RuleGrid rules={hard} /></section>
      <section className="panel overflow-hidden"><div className="flex items-center gap-3 border-b border-slate-100 bg-blue-50/60 p-5"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-100 text-blue-700"><Scale className="h-5 w-5" /></span><div><h3 className="text-base font-extrabold text-ink">优化目标</h3><p className="text-xs text-slate-500">S01-S03 · 在硬约束满足后继续优化</p></div></div><RuleGrid rules={soft} /></section>
    </div>
  )
}

function RuleGrid({ rules }: { rules: ReturnType<typeof useAppStore>['rules'] }) {
  return <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-3">{rules.map((rule) => { const copy = rulePresentation(rule.id, rule); return <article key={rule.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-center gap-2"><span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs font-black text-slate-700">{rule.id}</span><SlidersHorizontal className="ml-auto h-4 w-4 text-slate-300" /></div><h4 className="mt-3 text-sm font-extrabold text-ink">{copy.name}</h4><p className="mt-2 text-xs leading-5 text-slate-500">{copy.description}</p></article> })}</div>
}
