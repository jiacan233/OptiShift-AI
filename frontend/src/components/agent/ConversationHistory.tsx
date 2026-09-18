import { ChevronLeft, MessageSquareText } from 'lucide-react'
import { weekLabel } from '@/lib/isoWeek'
import type { ConversationSummary } from '@/types'

function dayGroup(value: string) {
  const date = new Date(value)
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const days = Math.round((start - target) / 86_400_000)
  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  return '更早'
}

export function ConversationHistory({
  conversations,
  currentId,
  disabled,
  onBack,
  onSelect,
}: {
  conversations: ConversationSummary[]
  currentId: string | null
  disabled?: boolean
  onBack(): void
  onSelect(id: string): void
}) {
  const groups = conversations.reduce<Record<string, ConversationSummary[]>>((result, conversation) => {
    const label = dayGroup(conversation.updated_at)
    result[label] = [...(result[label] ?? []), conversation]
    return result
  }, {})

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-slate-200 px-4 py-3">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-bold text-slate-600 hover:text-ink"><ChevronLeft className="h-4 w-4" />返回对话</button>
      </div>
      <div className="soft-scrollbar flex-1 overflow-y-auto p-4">
        {['今天', '昨天', '更早'].map((group) => groups[group]?.length ? (
          <section key={group} className="mb-5">
            <h3 className="mb-2 text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">{group}</h3>
            <div className="space-y-2">
              {groups[group].map((conversation) => (
                <button key={conversation.conversation_id} data-conversation-id={conversation.conversation_id} type="button" disabled={disabled} onClick={() => onSelect(conversation.conversation_id)} className={`w-full rounded-xl border p-3 text-left transition disabled:cursor-wait disabled:opacity-60 ${conversation.conversation_id === currentId ? 'border-teal-300 bg-teal-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
                  <p className="truncate text-sm font-extrabold text-slate-800">{conversation.title || '新对话'}</p>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                    {conversation.target_week && <span>{weekLabel(conversation.target_week)}</span>}
                    <span>{conversation.message_count} 条消息</span>
                  </div>
                  {conversation.last_message_preview && <p className="mt-1 truncate text-xs text-slate-400">{conversation.last_message_preview}</p>}
                </button>
              ))}
            </div>
          </section>
        ) : null)}
        {conversations.length === 0 && <div className="grid min-h-48 place-items-center text-center text-slate-400"><div><MessageSquareText className="mx-auto h-8 w-8" /><p className="mt-2 text-sm">还没有历史对话</p></div></div>}
      </div>
    </div>
  )
}
