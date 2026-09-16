import { AlertOctagon, Ban, ShieldAlert } from 'lucide-react'
import type { InfeasibleResult } from '@/types'

export function ConflictView({ result }: { result: InfeasibleResult }) {
  return (
    <section className="panel overflow-hidden border-red-200">
      <div className="flex items-start gap-3 bg-red-50 p-5">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-red-100 text-red-700"><AlertOctagon className="h-5 w-5" /></span>
        <div><p className="eyebrow !text-red-500">Primary Solver · INFEASIBLE</p><h2 className="mt-1 text-lg font-extrabold text-red-900">未生成非法排班</h2><p className="mt-1 text-sm text-red-700">{result.message ?? '当前条件无法满足全部硬约束。'}</p></div>
      </div>
      <div className="grid gap-4 p-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-extrabold text-ink"><ShieldAlert className="h-4 w-4 text-red-600" />覆盖缺口</h3>
          <div className="space-y-2">
            {result.conflicts.map((conflict, index) => (
              <div key={`${conflict.rule_id}-${conflict.day}-${conflict.shift}-${index}`} className="rounded-xl border border-red-100 bg-red-50/50 p-3">
                <div className="flex items-center justify-between"><span className="text-xs font-extrabold text-red-800">{conflict.rule_id} · {conflict.day} {conflict.shift}</span><span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">shortage {conflict.shortage}</span></div>
                <p className="mt-2 text-xs text-red-700">required {conflict.required} · available {conflict.available}</p>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-extrabold text-ink"><Ban className="h-4 w-4 text-amber-600" />候选人阻挡分析</h3>
          <div className="max-h-72 space-y-2 overflow-y-auto soft-scrollbar">
            {(result.blocking_candidates ?? []).map((candidate, index) => (
              <div key={`${candidate.employee_id}-${index}`} className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs font-extrabold text-slate-800">{candidate.employee_id} · {candidate.coverage_rule_id}</p>
                {candidate.reasons.map((reason, reasonIndex) => <p key={reasonIndex} className="mt-1 text-[11px] text-slate-500">{typeof reason === 'string' ? reason : `${reason.rule_id}: ${reason.message}`}</p>)}
              </div>
            ))}
            {(result.blocking_candidates ?? []).length === 0 && <p className="rounded-xl border border-dashed border-slate-200 p-5 text-center text-xs text-slate-400">没有额外的候选阻挡记录。</p>}
          </div>
        </div>
      </div>
    </section>
  )
}

