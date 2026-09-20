import { AlertOctagon, Ban, ShieldAlert } from 'lucide-react'
import { DAY_LABELS, localizeMessage, rulePresentation, SHIFT_LABELS } from '@/lib/presentation'
import type { InfeasibleResult } from '@/types'
import type { Employee } from '@/types'
import { ScheduleGrid } from '@/components/schedule/ScheduleGrid'

export function ConflictView({ result, employees = [], onDismiss, onClear, busy = false }: { result: InfeasibleResult; employees?: Employee[]; onDismiss?: () => void; onClear?: () => void; busy?: boolean }) {
  const conflicts = Array.isArray(result.conflicts) ? result.conflicts : []
  const diagnosisSummary = typeof result.diagnosis?.summary === 'string'
    ? localizeMessage(result.diagnosis.summary, result.diagnosis.summary)
    : null
  return (
    <section data-testid="scenario-preview" className="panel overflow-hidden border-red-200">
      <div className="flex flex-wrap gap-2 border-b border-red-100 p-3">
        {onDismiss && <button type="button" disabled={busy} onClick={onDismiss} className="btn-secondary" data-testid="dismiss-scenario">返回当前正式排班</button>}
        {onClear && result.status === 'scenario_preview' && <button type="button" disabled={busy} onClick={onClear} className="btn-secondary" data-testid="clear-scenario">结束本次试排</button>}
      </div>
      <div className="flex items-start gap-3 bg-red-50 p-5">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-red-100 text-red-700"><AlertOctagon className="h-5 w-5" /></span>
        <div><p className="eyebrow !text-red-500">{result.status === 'scenario_preview' ? 'Scenario Preview · 仅供试排' : '排班求解结果 · 当前不可行'}</p><h2 className="mt-1 text-lg font-extrabold text-red-900">{result.status === 'scenario_preview' && result.strict_feasible ? '场景试排可行' : '系统未生成正式排班'}</h2><p className="mt-1 text-sm text-red-700">{localizeMessage(result.message, '当前人员条件无法同时满足全部硬约束。')}</p>{result.scenario_revision !== undefined && <p className="mt-1 text-xs font-semibold text-red-600">场景版本 {result.scenario_revision} · 不会写入正式版本历史</p>}</div>
      </div>
      {result.preview_schedule && employees.length > 0 && <div className="border-t border-amber-200 bg-amber-50/40 p-5"><h3 className="mb-3 text-sm font-extrabold text-amber-900">最接近可行的试排结果</h3><ScheduleGrid schedule={result.preview_schedule} employees={employees} onSelectShift={() => undefined} /></div>}
      {Array.isArray(result.suggestions) && result.suggestions.length > 0 && <div className="border-t border-slate-200 bg-white p-5"><h3 className="mb-3 text-sm font-extrabold text-ink">候选调整建议</h3><div className="grid gap-2 md:grid-cols-2">{result.suggestions.slice(0, 4).map((suggestion) => <div key={String(suggestion.id ?? suggestion.suggestion_id)} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><p className="text-sm font-bold text-ink">{String(suggestion.title ?? '方案')}</p><p className="mt-1 text-xs leading-5 text-slate-600">{String(suggestion.description ?? '')}</p>{suggestion.based_on_scenario_revision !== undefined && <p className="mt-2 text-[11px] font-semibold text-teal-700">基于场景版本 {String(suggestion.based_on_scenario_revision)} · {((suggestion.validation_result as { strict_feasible?: boolean } | undefined)?.strict_feasible) ? '严格求解可行' : '严格求解仍不可行'}</p>}</div>)}</div></div>}
      <div className="grid gap-4 p-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-extrabold text-ink"><ShieldAlert className="h-4 w-4 text-red-600" />覆盖缺口</h3>
          <div className="space-y-2">
            {conflicts.map((conflict, index) => (
              <div key={`${conflict.rule_id}-${conflict.day}-${conflict.shift}-${index}`} className="rounded-xl border border-red-100 bg-red-50/50 p-3">
                <div className="flex items-center justify-between gap-2"><span className="text-xs font-extrabold text-red-800">{conflict.rule_id} · {rulePresentation(conflict.rule_id).name}</span><span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">缺少 {conflict.shortage} 人</span></div>
                <p className="mt-2 text-xs text-red-700">{DAY_LABELS[conflict.day]}{SHIFT_LABELS[conflict.shift]}：需要 {conflict.required} 人，当前可用 {conflict.available} 人</p>
              </div>
            ))}
            {conflicts.length === 0 && (
              <div className="rounded-xl border border-dashed border-red-200 bg-red-50/40 p-4 text-xs leading-5 text-red-700">
                <p className="font-bold">未发现单一的人员覆盖缺口。</p>
                <p className="mt-1">当前不可行来自其他保留硬约束，或多条硬约束之间的组合冲突。</p>
                {diagnosisSummary && <p className="mt-2">{diagnosisSummary}</p>}
              </div>
            )}
          </div>
        </div>
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-extrabold text-ink"><Ban className="h-4 w-4 text-amber-600" />候选人阻挡分析</h3>
          <div className="max-h-72 space-y-2 overflow-y-auto soft-scrollbar">
            {(result.blocking_candidates ?? []).map((candidate, index) => (
              <div key={`${candidate.employee_id}-${index}`} className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs font-extrabold text-slate-800">{candidate.employee_id} · {candidate.coverage_rule_id ? rulePresentation(candidate.coverage_rule_id).name : '候选员工'}</p>
                {candidate.reasons.map((reason, reasonIndex) => <p key={reasonIndex} className="mt-1 text-[11px] text-slate-500">{typeof reason === 'string' ? localizeMessage(reason, '该员工受其他硬约束限制。') : `${reason.rule_id} ${localizeMessage(reason.message, rulePresentation(reason.rule_id).name)}`}</p>)}
              </div>
            ))}
            {(result.blocking_candidates ?? []).length === 0 && <p className="rounded-xl border border-dashed border-slate-200 p-4 text-xs leading-5 text-slate-500">当前诊断未定位到单个可替换候选人。建议检查连续工作天数、晚转早、最大周班次数、员工可用性等保留硬约束的组合关系。</p>}
          </div>
        </div>
      </div>
    </section>
  )
}
