import { Check, LoaderCircle, Sparkles } from 'lucide-react'
import { MarkdownMessage } from '@/components/agent/MarkdownMessage'
import { CandidateMascot } from './CandidateMascot'
import type { CandidatePlan } from './types'

export function CandidateSummaryPanel({ plan, busy, onConfirm, onCancel, onViewAnalysis, onApplyPlan }: {
  plan: CandidatePlan | null
  busy: boolean
  onConfirm(): void
  onCancel(): void
  onViewAnalysis(): void
  onApplyPlan?: (plan: CandidatePlan) => void
}) {
  const result = plan?.result
  const explanation = typeof result?.explanation === 'string' ? result.explanation : result?.explanation?.text
  const validation = result?.validation
  const stale = validation?.employee_data_stale || validation?.rules_data_stale
  const force = plan?.version?.compliance_status === 'authorized_violations' || result?.compliance_status === 'authorized_violations' || validation?.compliance_status === 'authorized_violations' || !!validation?.authorized_violations?.length
  const confirmable = !stale && (validation?.confirmable ?? validation?.passed ?? false)
  const isDraft = plan?.kind === 'draft'
  const bullets = plan ? [
    `${plan.schedule.assignments.length} 条班次安排 · v${plan.schedule.version}`,
    ...(result ? [`偏好满足率 ${Math.round(result.metrics.preference_rate * 100)}% · 工作量差距 ${result.metrics.workload_gap} 班`] : []),
    ...(force && !validation ? [`非标准合规 · ${plan?.version?.authorized_violation_count ?? '待读取'} 项已授权规则冲突`] : []),
    ...(validation ? [stale ? '员工资料或标准规则已变更，请取消后重新生成' : force ? `非标准合规 · ${validation.authorized_violations?.length ?? 0} 项已授权规则冲突` : validation.passed ? `规则校验 ${validation.passed_count}/${validation.total} 项通过` : '存在规则冲突，请查看校验明细'] : []),
  ] : []
  return (
    <div className="bg-gradient-to-br from-blue-50/40 via-white to-purple-50/30 rounded-2xl p-3 border border-slate-200/80 shadow-2xs h-full flex flex-col justify-between relative overflow-hidden">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Sparkles className="w-3.5 h-3.5 text-blue-600" /><h3 className="text-xs font-black text-slate-800 tracking-tight">AI 生成说明</h3>
        {plan && <span className="text-[10px] text-slate-400 font-medium">· {new Date(plan.schedule.created_at).toLocaleString('zh-CN')}</span>}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 items-center mt-1.5">
        <div className="min-w-0 pr-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="bg-blue-100 text-blue-700 text-[10px] font-black px-1.5 py-0.5 rounded-md shrink-0">{isDraft ? '待确认' : plan?.kind === 'candidate' ? '备选' : '基准'}</span>
            <span className="text-xs font-extrabold text-slate-800">{isDraft ? `已生成草稿 v${plan.schedule.version}` : plan?.name ?? '等待排班方案'}</span>
          </div>
          <div className="mt-1.5 space-y-1">
            {bullets.map(bullet => <div key={bullet} className="flex items-start gap-1.5 text-[11px] text-slate-600 font-medium leading-relaxed"><span className="mt-1.5 h-1 w-1 rounded-full bg-blue-500 shrink-0" /><span>{bullet}</span></div>)}
            {!plan && <p className="text-[11px] leading-5 text-slate-500">生成排班后，在这里预览方案并确认生效。</p>}
          </div>
          {explanation && <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer font-bold text-blue-600">查看生成说明</summary><div className="mt-2 leading-5"><MarkdownMessage content={explanation} /></div></details>}
          {plan && !explanation && <p className="mt-1 text-[10px] text-slate-400">暂无生成说明</p>}
          {isDraft && <p className={`mt-2 text-[11px] leading-5 ${force || !confirmable ? 'text-amber-800' : 'text-slate-500'}`}>{force ? '确认后已授权违规仍会保留并随该版本生效。' : confirmable ? '确认后该排班版本正式生效。' : '草稿尚不能确认，请查看规则校验或取消后重新生成。'}</p>}
          <div className="flex flex-wrap items-center gap-2 mt-2.5">
            <button type="button" disabled={!plan || busy} onClick={onViewAnalysis} className="px-2.5 py-1 rounded-xl bg-white hover:bg-slate-50 border border-slate-200 text-blue-600 text-[11px] font-bold transition shadow-2xs disabled:opacity-40">查看更多分析</button>
            {isDraft ? <>
              <button type="button" disabled={busy} onClick={onCancel} className="px-2.5 py-1 rounded-xl bg-white hover:bg-slate-50 border border-slate-200 text-slate-600 text-[11px] font-bold disabled:opacity-40">取消草稿</button>
              <button type="button" aria-busy={busy} disabled={busy || !confirmable} onClick={onConfirm} className="inline-flex items-center gap-1 px-3 py-1 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-extrabold transition shadow-xs shadow-blue-500/20 disabled:opacity-40">{busy ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}{busy ? '正在处理…' : force ? '确认非合规强制方案' : '确认生效'}</button>
            </> : plan?.kind === 'current' ? <span className="text-[11px] font-bold text-slate-500">当前正式版本</span> : <button type="button" disabled={busy || !plan || !onApplyPlan || !!stale} onClick={() => { if (plan?.kind === 'candidate') onApplyPlan?.(plan) }} className="px-3 py-1 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-extrabold shadow-xs disabled:opacity-40">应用此方案</button>}
          </div>
        </div>
        <CandidateMascot />
      </div>
    </div>
  )
}
