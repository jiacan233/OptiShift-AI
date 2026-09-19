import { LoaderCircle, Sparkles } from 'lucide-react'
import type { CandidatePlan } from './types'
import { CandidatePlanCard } from './CandidatePlanCard'
import { CandidateSummaryPanel } from './CandidateSummaryPanel'

export function CandidatePlanSelector({ plans, selectedPlan, onSelectPlan, busy, loading, onConfirm, onCancel, onViewAnalysis, onApplyPlan }: {
  plans: CandidatePlan[]
  selectedPlan: CandidatePlan | null
  onSelectPlan(id: string): void
  busy: boolean
  loading: boolean
  onConfirm(): void
  onCancel(): void
  onViewAnalysis(): void
  // Leave undefined until a Candidate Apply / Promotion API is available.
  onApplyPlan?: (plan: CandidatePlan) => void
}) {
  return (
    <section id="schedule-plans" tabIndex={-1} aria-label="智能排班方案选择" aria-busy={loading} className="bg-white rounded-2xl border border-slate-200/80 p-3 shadow-xs scroll-mt-6">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 items-stretch">
        <div className="lg:col-span-7 flex flex-col justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded-md bg-blue-50 text-blue-600 flex items-center justify-center shrink-0"><Sparkles className="w-3.5 h-3.5" /></div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xs font-bold text-slate-900 tracking-tight">智能排班方案</h2>
              <span className="text-[11px] text-slate-400">预览排班与方案差异，确认后生效</span>
            </div>
          </div>
          {loading ? <p role="status" className="flex items-center gap-2 p-3 text-xs text-slate-500"><LoaderCircle className="h-4 w-4 animate-spin" />正在读取方案…</p> : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {plans.map(plan => <CandidatePlanCard key={plan.id} plan={plan} isSelected={plan.id === selectedPlan?.id} onSelect={onSelectPlan} disabled={busy} />)}
              {!plans.some(plan => plan.kind === 'candidate') && <div className="col-span-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-2.5 text-[11px] leading-5 text-slate-400">
                <p className="font-semibold text-slate-500">暂无候选方案</p>
                <p>多方案预览与应用暂未开放。</p>
              </div>}
            </div>
          )}
          {plans.some(plan => plan.kind === 'draft') && selectedPlan?.kind !== 'draft' && <button type="button" disabled={busy} onClick={() => { const draft = plans.find(plan => plan.kind === 'draft'); if (draft) onSelectPlan(draft.id) }} className="text-left text-[11px] font-bold text-blue-600 disabled:opacity-50">有待确认草稿 · 查看并处理</button>}
        </div>
        <div className="lg:col-span-5 min-h-[105px]">
          <CandidateSummaryPanel plan={loading ? null : selectedPlan} busy={busy || loading} onConfirm={onConfirm} onCancel={onCancel} onViewAnalysis={onViewAnalysis} onApplyPlan={onApplyPlan} />
        </div>
      </div>
    </section>
  )
}
