import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AlertCircle, Bot, History, LoaderCircle, MessageSquarePlus, Send, Sparkles, X } from 'lucide-react'
import { ConversationHistory } from '@/components/agent/ConversationHistory'
import { MessageBubble } from '@/components/agent/MessageBubble'
import { errorCodeLabel, problemMessage } from '@/lib/presentation'
import { weekLabel } from '@/lib/isoWeek'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import type { TrustedAgentAction } from '@/types'

const QUICK_QUESTIONS: Array<{ label: string; action?: TrustedAgentAction }> = [
  { label: '这周排班有什么可以优化的吗？', action: { intent: 'advice' } },
  { label: '为什么 E03 本周班次比较多？' },
  { label: '帮我检查当前排班有没有违反规则', action: { intent: 'validate' } },
  { label: 'E02 周五请假会有什么影响？', action: { intent: 'advice' } },
]

export function AgentPanel() {
  const agent = useAgentStore()
  const schedule = useAppStore()
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (agent.isChatOpen && !agent.isHistoryOpen) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [agent.isChatOpen, agent.isHistoryOpen, agent.isSending, agent.messages])

  if (!agent.isChatOpen) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const content = input.trim()
    if (!content) return
    setInput('')
    void agent.sendMessage(content)
  }

  return (
    <>
      <button type="button" className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-sm lg:hidden" onClick={agent.closeChat} aria-label="关闭 AI 助手" />
      <aside data-agent-panel="open" className="fixed inset-0 z-50 flex min-h-0 flex-col bg-slate-50 shadow-drawer lg:inset-y-0 lg:left-auto lg:right-0 lg:w-[380px] lg:border-l lg:border-slate-200 xl:w-[440px]" role="dialog" aria-modal="true" aria-label="OptiShift AI 智能排班助手">
        <header className="border-b border-slate-200 bg-white px-4 pb-3 pt-4 sm:px-5">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-teal-600 text-white"><Sparkles className="h-5 w-5" /></span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-black text-ink">OptiShift AI</h2>
              <p className="text-xs text-slate-500">智能排班助手 · 当前上下文：{weekLabel(schedule.activeWeekStart)}</p>
            </div>
            <button type="button" onClick={agent.closeChat} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="关闭 AI 助手"><X className="h-5 w-5" /></button>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={() => void agent.showHistory()} disabled={agent.isSending} className="btn-secondary !rounded-lg !px-3 !py-1.5 !text-xs"><History className="h-3.5 w-3.5" />历史</button>
            <button type="button" onClick={() => void agent.newConversation()} disabled={agent.isSending || agent.isLoadingConversation} className="btn-secondary !rounded-lg !px-3 !py-1.5 !text-xs"><MessageSquarePlus className="h-3.5 w-3.5" />新对话</button>
            <span className="ml-auto flex items-center gap-1.5 text-[10px] font-semibold text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${agent.agentError ? 'bg-red-400' : agent.isSending ? 'bg-amber-400' : 'bg-emerald-500'}`} />{agent.isSending ? '正在保存' : agent.agentError ? '保存失败' : '服务端已保存'}</span>
          </div>
          {!agent.isHistoryOpen && <p className="mt-3 truncate text-sm font-bold text-slate-700">{agent.conversationTitle || '新对话'}</p>}
        </header>

        {agent.isHistoryOpen ? (
          <ConversationHistory conversations={agent.conversations} currentId={agent.conversationId} disabled={agent.isLoadingConversation || agent.isSending} onBack={agent.hideHistory} onSelect={(id) => void agent.loadConversation(id).catch(() => undefined)} />
        ) : (
          <>
            <div className="soft-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5">
              {agent.isLoadingConversation ? (
                <div className="grid min-h-full place-items-center text-sm text-slate-500"><LoaderCircle className="mb-2 h-6 w-6 animate-spin text-teal-600" />正在恢复对话…</div>
              ) : agent.messages.length === 0 ? (
                <div className="flex min-h-full flex-col justify-center">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-teal-100 text-teal-700"><Bot className="h-6 w-6" /></span>
                  <h3 className="mt-4 text-lg font-black text-ink">你好，我是排班助手</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-500">我可以帮你分析、解释和调整当前排班。排班调整只会生成草稿，正式生效仍需你点击“确认变更”。</p>
                  <div className="mt-5 space-y-2">
                    {QUICK_QUESTIONS.map((item) => (
                      <button key={item.label} type="button" disabled={agent.isLoadingConversation || agent.isSending} onClick={() => void agent.sendMessage(item.label, item.action && { ...item.action, target_week: schedule.activeWeekStart })} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-xs font-semibold leading-5 text-slate-700 transition hover:border-teal-300 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50">
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {agent.messages.map((message) => (
                    <MessageBubble key={message.message_id} message={message} trace={agent.tracesByMessage[message.message_id] ?? []} suggestionsDisabled={agent.isSending || agent.isLoadingConversation} onApplySuggestion={(suggestion) => {
                      if (suggestion.action === 'generate' || !suggestion.based_on_schedule_id) {
                        void agent.sendMessage(`按 ${suggestion.suggestion_id} 生成草稿。`, { intent: 'generate', target_week: suggestion.target_week ?? schedule.activeWeekStart })
                        return
                      }
                      void agent.sendMessage(`按 ${suggestion.suggestion_id} 调整。`)
                    }} />
                  ))}
                  {agent.isSending && <div className="flex items-center gap-2 text-xs font-semibold text-slate-400"><LoaderCircle className="h-4 w-4 animate-spin text-teal-600" />正在读取真实排班上下文…</div>}
                  <div ref={endRef} />
                </div>
              )}
            </div>

            {agent.agentError && (
              <div className="mx-4 mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-red-800 sm:mx-5">
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><div><p className="text-xs font-black">{errorCodeLabel(agent.agentError.code)}</p><p className="mt-0.5 text-xs leading-5">{problemMessage(agent.agentError.code, agent.agentError.message)}</p></div><button type="button" onClick={agent.dismissError} className="ml-auto"><X className="h-3.5 w-3.5" /></button></div>
                {agent.pendingMessage && <button type="button" onClick={() => void agent.retryPendingMessage()} disabled={agent.isSending} className="mt-2 text-xs font-black text-red-700 underline">使用同一请求标识重试</button>}
              </div>
            )}

            <form onSubmit={submit} className="border-t border-slate-200 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-4">
              <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-100">
                <textarea value={input} disabled={agent.isLoadingConversation} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} rows={2} placeholder="问排班、规则，或描述需要调整的内容…" className="max-h-32 min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed" />
                <button type="submit" disabled={!input.trim() || agent.isSending || agent.isLoadingConversation} className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-teal-600 text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40" aria-label="发送消息">{agent.isSending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
              </div>
              <p className="mt-2 text-center text-[10px] text-slate-400">Enter 发送 · Shift + Enter 换行</p>
            </form>
          </>
        )}
      </aside>
    </>
  )
}
