import { ArrowLeftRight } from 'lucide-react'
import { DAY_LABELS, SHIFT_LABELS } from '@/lib/presentation'
import type { CandidatePlan } from './types'

export function CandidateComparisonBar({ plan, baseline }: { plan: CandidatePlan | null; baseline: CandidatePlan | null }) {
  if (!plan || plan.kind === 'current') return null
  const diff = plan.result?.diff
  return <section aria-label="方案对比与优劣势分析" className="bg-white rounded-[28px] border border-slate-200/80 p-4 md:p-5 shadow-soft">
    <div className="flex flex-col xl:flex-row gap-5 xl:items-center">
      <div className="flex items-center gap-3 shrink-0"><span className="w-11 h-11 rounded-2xl bg-blue-600 text-white flex items-center justify-center shadow-md shadow-blue-500/20"><ArrowLeftRight className="h-5 w-5" /></span><div><h3 className="text-sm font-extrabold text-slate-900">方案对比</h3><p className="text-[11px] text-slate-400">相比当前正式排班</p></div></div>
      <div className="flex-1 grid gap-3 md:grid-cols-3 bg-slate-50/60 rounded-2xl p-3 border border-slate-200/80">
        {[baseline, plan].map((item, index) => <div key={item?.id ?? 'baseline'} className={`bg-white rounded-xl p-3 border shadow-2xs ${index ? 'border-blue-200 ring-1 ring-blue-100' : 'border-slate-200'}`}><h4 className="text-xs font-black text-slate-900">{item?.name ?? '暂无正式版'}</h4><p className="mt-2 text-[11px] text-slate-500">班次安排 <strong className="text-sm text-slate-800">{item?.schedule.assignments.length ?? '—'}</strong></p><p className="mt-1 text-[11px] text-slate-500">偏好满足率 <strong className="text-slate-800">{item?.result ? `${Math.round(item.result.metrics.preference_rate * 100)}%` : '—'}</strong></p></div>)}
        <div className="p-1 text-[11px] leading-5 text-slate-600"><h4 className="mb-1 text-xs font-extrabold text-slate-800">关键差异</h4>{diff ? <><p>新增 {diff.added.length} 条 · 移除 {diff.removed.length} 条</p><p>影响 {diff.affected_employees.length} 位员工 · {diff.changed_shifts} 个班次</p><details className="mt-1"><summary className="cursor-pointer font-bold text-blue-600">查看方案差异明细</summary><ul className="mt-2 space-y-1">{diff.shifts.filter(shift => shift.added.length || shift.removed.length).map(shift => <li key={`${shift.day}-${shift.shift}`}>{DAY_LABELS[shift.day]} {SHIFT_LABELS[shift.shift]}{shift.added.length ? ` · 新增 ${shift.added.join('、')}` : ''}{shift.removed.length ? ` · 移除 ${shift.removed.join('、')}` : ''}</li>)}</ul></details></> : <p>{baseline ? '暂无方案差异数据' : '首次生成，无正式版可对比'}</p>}</div>
      </div>
    </div>
  </section>
}
