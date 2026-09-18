import { AlertTriangle } from 'lucide-react'
import { DAY_LABELS, localizeMessage, rulePresentation, SHIFT_LABELS } from '@/lib/presentation'
import { weekLabel } from '@/lib/isoWeek'
import type { AgentMessage, BlockingCandidate, Conflict } from '@/types'

function reasonText(reason: BlockingCandidate['reasons'][number]) {
  if (typeof reason === 'string') return localizeMessage(reason, '该员工受其他硬约束限制。')
  return `${rulePresentation(reason.rule_id).name}：${localizeMessage(reason.message, '该员工受其他硬约束限制。')}`
}

export function InfeasibleSummary({ message }: { message: AgentMessage }) {
  const result = message.metadata_json?.infeasible_result
  if (!result || (result.status === 'scenario_preview' && result.strict_feasible)) return null
  if (!result || !['infeasible', 'scenario_preview'].includes(result.status)) return null
  const conflicts: Conflict[] = Array.isArray(result.conflicts) ? result.conflicts.slice(0, 3) : []
  const candidates: BlockingCandidate[] = Array.isArray(result.blocking_candidates)
    ? result.blocking_candidates.slice(0, 5)
    : []
  const diagnosisSummary = typeof result.diagnosis?.summary === 'string'
    ? localizeMessage(result.diagnosis.summary, result.diagnosis.summary)
    : null
  let targetLabel = '当前周'
  if (message.target_week) {
    try {
      targetLabel = weekLabel(message.target_week)
    } catch {
      targetLabel = message.target_week
    }
  }

  return (
    <section className="mt-3 rounded-xl border border-red-100 bg-red-50/60 p-3" data-testid="infeasible-summary">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <div className="min-w-0">
          <p className="text-xs font-extrabold text-red-900">{result.status === 'scenario_preview' ? `场景试排结果 · ${targetLabel}` : `当前约束下无法生成${targetLabel}排班`}</p>
          {result.message && <p className="mt-1 text-[11px] leading-5 text-red-700">{localizeMessage(result.message, result.message)}</p>}
        </div>
      </div>
      {conflicts.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] font-extrabold text-red-800">主要冲突</p>
          {conflicts.map((conflict, index) => (
            <div key={`${conflict.rule_id}-${conflict.day}-${conflict.shift}-${index}`} className="rounded-lg border border-red-100 bg-white/70 px-2.5 py-2">
              <p className="text-[11px] font-bold text-slate-800">{conflict.rule_id} · {rulePresentation(conflict.rule_id).name}</p>
              <p className="mt-0.5 text-[11px] text-slate-600">{DAY_LABELS[conflict.day]}{SHIFT_LABELS[conflict.shift]} · 需要 {conflict.required} 人 · 当前可用 {conflict.available} 人 · 缺少 {conflict.shortage} 人</p>
            </div>
          ))}
        </div>
      )}
      {conflicts.length === 0 && (
        <div className="mt-3 text-[11px] leading-5 text-slate-600">
          <p>未发现单一的人员覆盖缺口，当前不可行可能来自其他保留硬约束或多条硬约束的组合。</p>
          {diagnosisSummary && <p className="mt-1">{diagnosisSummary}</p>}
        </div>
      )}
      {candidates.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] font-extrabold text-slate-700">候选人阻挡</p>
          {candidates.map((candidate, index) => (
            <div key={`${candidate.employee_id}-${index}`} className="rounded-lg border border-slate-200 bg-white/70 px-2.5 py-2">
              <p className="text-[11px] font-bold text-slate-800">{candidate.employee_id}</p>
              {candidate.reasons.slice(0, 2).map((reason, reasonIndex) => <p key={reasonIndex} className="mt-0.5 text-[11px] text-slate-500">• {reasonText(reason)}</p>)}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
