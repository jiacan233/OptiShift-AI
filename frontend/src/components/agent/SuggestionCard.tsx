import { ArrowRight } from 'lucide-react'
import type { AgentSuggestion, SuggestionExecution } from '@/types'

export function SuggestionCard({ suggestion, ordinal, disabled = false, draftBlocked = false, onApply }: {
  suggestion: AgentSuggestion
  ordinal: number
  disabled?: boolean
  draftBlocked?: boolean
  onApply(suggestion: AgentSuggestion, execution: SuggestionExecution): void
}) {
  const missingIdentity = !suggestion.suggestion_set_id
  const unavailable = disabled || missingIdentity || suggestion.stale === true || suggestion.executable === false
  const actions: Array<{ execution: SuggestionExecution; label: string; testId: string }> = [
    { execution: 'record', label: '仅采纳', testId: 'apply' },
    { execution: 'preview', label: '采纳并试排', testId: 'preview' },
    { execution: 'create_draft', label: '采纳并生成草稿', testId: 'create-draft' },
  ]
  return (
    <article data-suggestion-id={suggestion.suggestion_id} data-suggestion-set-id={suggestion.suggestion_set_id} className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50/40 via-white to-purple-50/30 p-3">
      <p className="text-[10px] font-black text-blue-700">建议 {suggestion.display_order ?? suggestion.ordinal ?? ordinal}</p>
      {suggestion.title && <h4 className="mt-1 text-sm font-extrabold text-slate-800">{suggestion.title}</h4>}
      <p className="mt-1 text-xs leading-5 text-slate-600">{suggestion.content ?? suggestion.description}</p>
      {suggestion.stale ? <p className="mt-2 text-xs text-amber-800">这条建议已失效，请重新获取建议。</p> : missingIdentity ? <p className="mt-2 text-xs text-amber-800">旧建议缺少可验证的来源，请重新获取建议。</p> : suggestion.executable === false ? <p className="mt-2 text-xs text-slate-500">咨询建议，不能直接采纳。</p> : null}
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-2">{actions.map(action => <button key={action.execution} data-testid={`${action.testId}-${suggestion.suggestion_id}`} type="button" disabled={unavailable || (draftBlocked && action.execution === 'create_draft')} onClick={() => onApply(suggestion, action.execution)} className="inline-flex items-center gap-1 text-xs font-bold text-blue-700 hover:text-blue-800 disabled:cursor-not-allowed disabled:opacity-45">
        {action.label} <ArrowRight className="h-3.5 w-3.5" />
      </button>)}</div>
      {draftBlocked && <p className="mt-2 text-[11px] text-slate-500">已有待确认草稿，可以记录或试排；生成前请先到工作台处理草稿。</p>}
    </article>
  )
}
