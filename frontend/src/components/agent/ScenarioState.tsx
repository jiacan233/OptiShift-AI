import type { AgentScenario, DialogueCondition, DialoguePending, DialogueStaffingConstraint, ScheduleChange } from '@/types'
import { DAY_LABELS as DAYS, SHIFT_LABELS as SHIFTS } from '@/lib/presentation'
const ACTIONS: Record<ScheduleChange['type'], string> = {
  leave: '请假', unavailable: '不可排', available: '允许排班', preference: '优先', assign: '安排上班', unassign: '移出班次',
}

function conditionText(condition: DialogueCondition) {
  const first = condition.changes[0]
  if (first && first.candidate_days && first.candidate_days.length && first.work_day_count) {
    const candDays = first.candidate_days.map(d => DAYS[d] || d).join('、')
    const shiftStr = first.shift ? SHIFTS[first.shift] : '班次自选'
    return `${first.employee_id} ${candDays}任选${first.work_day_count}天 ${shiftStr} ${ACTIONS[first.type] || first.type}`
  }
  return condition.changes.map(change => {
    const shiftStr = change.shift ? SHIFTS[change.shift] : (change.type === 'assign' ? '班次自选' : '全天')
    return `${change.employee_id} ${DAYS[change.day]}${shiftStr} ${ACTIONS[change.type]}`
  }).join('；')
}

function pendingText(pending: DialoguePending) {
  if (pending.prompt) return pending.prompt
  if (pending.kind === 'force_staffing') return pending.prompt || '请确认是否按低于 R04 最低人数的要求生成方案。'
  const hasDays = (pending.days && pending.days.length > 0) || (pending.candidate_days && pending.candidate_days.length > 0 && pending.work_day_count != null)
  const missing = [
    !pending.employee_id && '员工',
    !pending.type && '调整方式',
    !hasDays && '日期',
    pending.type && ['assign', 'unassign', 'preference'].includes(pending.type) && !pending.shift && pending.shift_mode !== 'FLEXIBLE' && '班次',
  ].filter(Boolean)
  const daysDesc = pending.candidate_days && pending.candidate_days.length && pending.work_day_count
    ? `${pending.candidate_days.map(d => DAYS[d] || d).join('、')}任选${pending.work_day_count}天`
    : (pending.work_day_count && (!pending.days || pending.days.length === 0)
       ? `安排${pending.work_day_count}天`
       : pending.days?.map(day => DAYS[day]).join('、'))
  const shiftDesc = pending.shift ? SHIFTS[pending.shift] : (pending.shift_mode === 'FLEXIBLE' ? '班次自选' : null)
  const known = [pending.employee_id, daysDesc, shiftDesc, pending.type && ACTIONS[pending.type]].filter(Boolean).join(' ')
  return `${known || '排班调整'} · 还需补充${missing.join('、') || '具体要求'}`
}

function staffingText(c: DialogueStaffingConstraint) {
  const scope = c.days.map(day => DAYS[day]).join('、') + (c.scope === 'DAY' ? '全天合计' : c.shifts.map(shift => SHIFTS[shift]).join('、'))
  const bounds = c.min_count != null && c.min_count === c.max_count
    ? `恰好 ${c.min_count} 人`
    : [c.min_count != null && `至少 ${c.min_count} 人`, c.target_count != null && `目标 ${c.target_count} 人`, c.max_count != null && `最多 ${c.max_count} 人`].filter(Boolean).join('，')
  return `${scope}：${bounds}`
}

export function ScenarioState({ scenario }: { scenario: AgentScenario | null }) {
  const state = scenario?.dialogue_state
  const staffing = state?.staffing_constraints ?? []
  const proposedStaffing = state?.proposed_staffing ?? []
  if (!state || !(staffing.length || proposedStaffing.length || state.conditions.length || state.pending.length || state.proposals.length || state.conflicts.length || state.warnings.length)) return null
  return (
    <section aria-label="当前排班条件" data-testid="dialogue-state" className="mb-4 space-y-3 rounded-xl border border-blue-100 bg-white p-3 text-xs text-slate-700">
      <p className="font-bold text-slate-900">当前排班条件 <span className="font-normal text-slate-500">· {scenario.target_week} 当周</span></p>
      <div>
        <p className="font-semibold text-emerald-800">已记录 · {state.conditions.length + staffing.length} 项要求</p>
        {state.conditions.length ? <ol className="mt-1 list-inside list-decimal space-y-1">{state.conditions.map(condition => <li key={condition.id}>{conditionText(condition)}</li>)}</ol> : !staffing.length && <p className="mt-1 text-slate-500">暂无已采纳条件。</p>}
        {!!staffing.length && <ul className="mt-1 space-y-1">{staffing.map((c, i) => <li key={i}>{staffingText(c)}</li>)}</ul>}
      </div>
      {!!proposedStaffing.length && <div><p className="font-semibold">人数分析提案 · 尚未采纳</p><ul>{proposedStaffing.map((c, i) => <li key={i}>{staffingText(c)}</li>)}</ul></div>}
      {state.proposed_staffing != null && !proposedStaffing.length && <p>人数分析提案：清除附加人数要求，尚未采纳。</p>}
      {!!state.proposals.length && <div><p className="font-semibold">分析提案 · 尚未采纳</p><ul className="mt-1 space-y-1">{state.proposals.map(proposal => <li key={proposal.id}>{conditionText(proposal)}</li>)}</ul></div>}
      {!!state.pending.length && <div className="rounded-lg bg-amber-50 p-2 text-amber-900"><p className="font-semibold">待确认 / 待补信息</p><ul className="mt-1 space-y-1">{state.pending.map(pending => <li key={pending.id}>{pendingText(pending)}</li>)}</ul></div>}
      {!!state.conflicts.length && <div role="status" className="rounded-lg bg-red-50 p-2 text-red-800"><p className="font-semibold">解决冲突后才能执行</p><ul className="mt-1 space-y-1">{state.conflicts.map((conflict, index) => <li key={`${conflict.code}-${index}`}>{conflict.message || '条件之间存在冲突，请在对话中说明保留或取消哪项。'}</li>)}</ul></div>}
      {!!state.warnings.length && <ul className="space-y-1 text-amber-800">{state.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
    </section>
  )
}
