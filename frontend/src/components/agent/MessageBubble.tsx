import { Bot, CircleCheck, CircleX, FileEdit } from 'lucide-react'
import { AgentTrace } from '@/components/agent/AgentTrace'
import { SuggestionCard } from '@/components/agent/SuggestionCard'
import type { AgentMessage, AgentSuggestion, AgentToolCall } from '@/types'

export function MessageBubble({
  message,
  trace,
  suggestionsDisabled = false,
  onApplySuggestion,
}: {
  message: AgentMessage
  trace: AgentToolCall[]
  suggestionsDisabled?: boolean
  onApplySuggestion(suggestion: AgentSuggestion): void
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[86%] rounded-2xl rounded-br-md bg-teal-600 px-4 py-3 text-sm leading-6 text-white shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  const suggestions = message.metadata_json?.suggestions ?? []
  const draftVersion = message.metadata_json?.generated_draft_version
  const recoveredStatus = message.metadata_json?.recovered_schedule_status
  const draftNotice = recoveredStatus === 'confirmed'
    ? `排班 v${draftVersion} 已确认`
    : recoveredStatus === 'cancelled'
      ? `排班草稿 v${draftVersion} 已取消`
      : `已生成待确认草稿 v${draftVersion}`
  const DraftStatusIcon = recoveredStatus === 'confirmed'
    ? CircleCheck
    : recoveredStatus === 'cancelled'
      ? CircleX
      : FileEdit
  const draftNoticeStyle = recoveredStatus === 'confirmed'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
    : recoveredStatus === 'cancelled'
      ? 'border-slate-200 bg-slate-100 text-slate-700'
      : 'border-amber-200 bg-amber-50 text-amber-800'
  return (
    <div className="flex items-start gap-2.5">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-ink text-white"><Bot className="h-4 w-4" /></span>
      <div className="min-w-0 max-w-[88%]">
        <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-700 shadow-sm whitespace-pre-wrap">
          {message.content}
          {draftVersion && (
            <div className={`mt-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${draftNoticeStyle}`}>
              <DraftStatusIcon className="h-4 w-4" /> {draftNotice}
            </div>
          )}
          {suggestions.length > 0 && <div className="mt-3 space-y-2">{suggestions.map((suggestion) => <SuggestionCard key={suggestion.suggestion_id} suggestion={suggestion} disabled={suggestionsDisabled} onApply={onApplySuggestion} />)}</div>}
          <AgentTrace calls={trace} />
        </div>
        <p className="mt-1 px-1 text-[10px] text-slate-400">{new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</p>
      </div>
    </div>
  )
}
