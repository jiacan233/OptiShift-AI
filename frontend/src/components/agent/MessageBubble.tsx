import { ArrowUpRight } from 'lucide-react'
import { InfeasibleSummary } from '@/components/agent/InfeasibleSummary'
import { MarkdownMessage } from '@/components/agent/MarkdownMessage'
import { AgentTrace } from '@/components/agent/AgentTrace'
import { SuggestionCard } from '@/components/agent/SuggestionCard'
import type { AgentMessage, AgentSuggestion, AgentToolCall } from '@/types'

export function MessageBubble({ message, trace, suggestionsDisabled = false, onApplySuggestion, onViewPlan }: {
  message: AgentMessage
  trace: AgentToolCall[]
  suggestionsDisabled?: boolean
  onApplySuggestion(suggestion: AgentSuggestion): void
  onViewPlan(): void
}) {
  const isUser = message.role === 'user'
  const suggestions = message.metadata_json?.suggestions ?? []
  const draftVersion = message.metadata_json?.generated_draft_version
  const recoveredStatus = message.metadata_json?.recovered_schedule_status
  return (
    <div className={`flex min-w-0 flex-col ${isUser ? 'items-end' : 'items-start'}`}>
      <div className="mb-1 flex items-center gap-2 px-1">
        <span className="text-[10px] font-medium text-slate-400">{new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
        <span className="text-[11px] font-bold text-slate-600">{isUser ? '排班经理' : 'OptiShift AI'}</span>
      </div>
      {isUser ? <div className="max-w-[85%] whitespace-pre-wrap break-words bg-blue-600 text-white rounded-2xl rounded-tr-sm p-3 text-xs font-medium shadow-md shadow-blue-500/15 leading-relaxed">{message.content}</div> : (
        <div className="min-w-0 max-w-[95%] break-words bg-white border border-slate-200/80 rounded-2xl rounded-tl-sm p-3.5 shadow-sm text-xs leading-relaxed text-slate-800">
          <MarkdownMessage content={message.content} />
          <InfeasibleSummary message={message} />
          {draftVersion != null && <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
            <span>本轮排班版本 v{draftVersion}{recoveredStatus === 'confirmed' ? ' · 已确认' : recoveredStatus === 'cancelled' ? ' · 已取消' : ''}</span>
            <button type="button" onClick={onViewPlan} className="mt-1 flex items-center gap-1 font-bold text-blue-600 hover:text-blue-700">查看工作台方案 <ArrowUpRight className="h-3 w-3" /></button>
          </div>}
          {suggestions.length > 0 && <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70"><summary className="cursor-pointer px-3 py-2 text-[11px] font-bold text-blue-700">调整建议 · {suggestions.length} 条</summary><div className="space-y-2 border-t border-slate-200/60 p-2">{suggestions.map(suggestion => <SuggestionCard key={suggestion.suggestion_id} suggestion={suggestion} disabled={suggestionsDisabled} onApply={onApplySuggestion} />)}</div></details>}
          <AgentTrace calls={trace} events={message.metadata_json?.execution_events ?? []} />
        </div>
      )}
    </div>
  )
}
