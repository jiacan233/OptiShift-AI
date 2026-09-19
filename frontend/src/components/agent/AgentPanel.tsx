import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Activity, AlertCircle, Bot, CheckCircle2, History, LoaderCircle, MessageSquarePlus, Send, Sparkles, X } from 'lucide-react'
import { AgentTrace } from '@/components/agent/AgentTrace'
import { ConversationHistory } from '@/components/agent/ConversationHistory'
import { MessageBubble } from '@/components/agent/MessageBubble'
import { api, apiErrorMessage, type LlmHealthResult } from '@/api/client'
import { errorCodeLabel, problemDetail, problemMessage } from '@/lib/presentation'
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
  const busy = agent.isSending || agent.isLoadingConversation || schedule.isBootstrapping || schedule.isRunning || schedule.isLoadingWeek || !!schedule.isSavingEmployee
  const [input, setInput] = useState('')
  const [llmHealth, setLlmHealth] = useState<LlmHealthResult | null>(null)
  const [llmHealthError, setLlmHealthError] = useState<string | null>(null)
  const [isCheckingLlm, setCheckingLlm] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (agent.isChatOpen && !agent.isHistoryOpen) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [agent.isChatOpen, agent.isHistoryOpen, agent.isSending, agent.messages, agent.executionEvents])

  if (!agent.isChatOpen) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const content = input.trim()
    if (!content || busy) return
    setInput('')
    void agent.sendMessage(content)
  }
  const errorDetail = agent.agentError
    ? problemDetail(agent.agentError.code, agent.agentError.details)
    : null
  const basicCheck = llmHealth?.checks.basic_chat
  const structuredCheck = llmHealth?.checks.structured_output
  const structuredReady = basicCheck?.status === 'ok' && structuredCheck?.status === 'ok'

  const checkLlm = async () => {
    if (isCheckingLlm) return
    setCheckingLlm(true)
    setLlmHealth(null)
    setLlmHealthError(null)
    try {
      setLlmHealth(await api.health.checkLlm())
    } catch (error) {
      setLlmHealthError(apiErrorMessage(error).message)
    } finally {
      setCheckingLlm(false)
    }
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
            <button type="button" onClick={() => void agent.showHistory()} disabled={busy} className="btn-secondary !rounded-lg !px-3 !py-1.5 !text-xs"><History className="h-3.5 w-3.5" />历史</button>
            <button type="button" onClick={() => void agent.newConversation()} disabled={busy} className="btn-secondary !rounded-lg !px-3 !py-1.5 !text-xs"><MessageSquarePlus className="h-3.5 w-3.5" />新对话</button>
            <button type="button" onClick={() => void checkLlm()} disabled={isCheckingLlm} className="btn-secondary ml-auto !rounded-lg !px-3 !py-1.5 !text-xs" aria-label="检测 AI 联通状态">
              {isCheckingLlm ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
              {isCheckingLlm ? '检测中' : '检测 AI'}
            </button>
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[10px] font-semibold text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${agent.agentError ? 'bg-red-400' : agent.isSending ? 'bg-amber-400' : 'bg-emerald-500'}`} />{agent.isSending ? '正在保存' : agent.agentError ? '保存失败' : '服务端已保存'}</div>
          {(isCheckingLlm || llmHealth || llmHealthError) && (
            <div aria-live="polite" className={`mt-2 rounded-lg border px-3 py-2 text-xs ${structuredReady ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : isCheckingLlm ? 'border-slate-200 bg-slate-50 text-slate-600' : 'border-red-200 bg-red-50 text-red-800'}`}>
              {isCheckingLlm ? (
                <span className="flex items-center gap-2"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />正在连接 AI Provider…</span>
              ) : structuredReady ? (
                <div className="flex items-start gap-2"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div><p className="font-black">AI 联通正常</p><p className="mt-0.5 text-[10px]">模型：{llmHealth?.model ?? ''}</p><p className="mt-0.5 text-[10px]">基础聊天：✓ {basicCheck?.latency_ms ?? 0} ms</p><p className="mt-0.5 text-[10px]">结构化输出：✓ {structuredCheck?.latency_ms ?? 0} ms</p></div></div>
              ) : llmHealth ? (
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div>
                  <p className="font-black">{basicCheck?.status === 'ok' ? 'AI 基础连接正常' : 'AI 联通失败'}</p>
                  {basicCheck?.status === 'ok' && structuredCheck?.status !== 'ok' ? <p className="mt-0.5 leading-5">Agent 结构化输出不可用</p> : <p className="mt-0.5 leading-5">{basicCheck?.message || structuredCheck?.message || 'AI Provider 暂时不可用。'}</p>}
                  {structuredCheck?.status !== 'ok' && structuredCheck && <p className="mt-0.5 leading-5">{structuredCheck.provider_message || structuredCheck.message || ''}</p>}
                  {basicCheck?.status !== 'ok' && basicCheck && <p className="mt-0.5 leading-5">{basicCheck.provider_message || ''}</p>}
                  {(() => { const check = basicCheck?.status === 'ok' ? structuredCheck : basicCheck; return <p className="mt-0.5 font-mono text-[10px]">{check?.provider_status ? `HTTP ${check.provider_status} · ` : ''}{check?.error_type || 'provider_error'}{check?.latency_ms != null ? ` · ${check.latency_ms} ms` : ''}</p> })()}
                </div></div>
              ) : (
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div><p className="font-black">无法执行检测</p><p className="mt-0.5 leading-5">{llmHealthError}</p></div></div>
              )}
            </div>
          )}
          {!agent.isHistoryOpen && <p className="mt-3 truncate text-sm font-bold text-slate-700">{agent.conversationTitle || '新对话'}</p>}
        </header>

        {agent.isHistoryOpen ? (
          <ConversationHistory conversations={agent.conversations} currentId={agent.conversationId} disabled={busy} onBack={agent.hideHistory} onSelect={(id) => void agent.loadConversation(id).catch(() => undefined)} />
        ) : (
          <>
            <div className="soft-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5">
              {agent.isLoadingConversation ? (
                <div className="grid min-h-full place-items-center text-sm text-slate-500"><LoaderCircle className="mb-2 h-6 w-6 animate-spin text-teal-600" />正在恢复对话…</div>
              ) : agent.messages.length === 0 && !agent.pendingMessage && !agent.isSending ? (
                <div className="flex min-h-full flex-col justify-center">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-teal-100 text-teal-700"><Bot className="h-6 w-6" /></span>
                  <h3 className="mt-4 text-lg font-black text-ink">你好，我是排班助手</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-500">我可以帮你分析、解释和调整当前排班。排班调整只会生成草稿，正式生效仍需你点击“确认变更”。</p>
                  <div className="mt-5 space-y-2">
                    {QUICK_QUESTIONS.map((item) => (
                      <button key={item.label} type="button" disabled={busy} onClick={() => void agent.sendMessage(item.label, item.action && { ...item.action, target_week: schedule.activeWeekStart })} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-xs font-semibold leading-5 text-slate-700 transition hover:border-teal-300 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50">
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {agent.messages.map((message) => (
                    <MessageBubble key={message.message_id} message={message} trace={agent.tracesByMessage[message.message_id] ?? []} suggestionsDisabled={busy} onApplySuggestion={(suggestion) => {
                      if (suggestion.action === 'generate' || !suggestion.based_on_schedule_id) {
                        void agent.sendMessage(`按 ${suggestion.suggestion_id} 生成草稿。`, { intent: 'generate', target_week: suggestion.target_week ?? schedule.activeWeekStart })
                        return
                      }
                      void agent.sendMessage(`按 ${suggestion.suggestion_id} 调整。`)
                    }} />
                  ))}

                </div>
              )}
              {agent.pendingMessage && !agent.messages.some((message) => message.client_message_id === agent.pendingMessage?.clientMessageId) && <div className="mt-4 rounded-2xl bg-teal-600 p-3 text-sm text-white">{agent.pendingMessage.content}</div>}
              <AgentTrace calls={[]} events={agent.executionEvents} running={agent.isSending} />
              <div ref={endRef} />
            </div>

            {agent.agentError && (
              <div className="mx-4 mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-red-800 sm:mx-5">
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><div><p className="text-xs font-black">{errorCodeLabel(agent.agentError.code)}</p><p className="mt-0.5 text-xs leading-5">{problemMessage(agent.agentError.code, agent.agentError.message)}</p>{errorDetail && <p className="mt-1 font-mono text-[10px] text-red-600">{errorDetail}</p>}</div><button type="button" onClick={agent.dismissError} className="ml-auto"><X className="h-3.5 w-3.5" /></button></div>
                {agent.pendingMessage && <button type="button" onClick={() => void agent.retryPendingMessage()} disabled={busy} className="mt-2 text-xs font-black text-red-700 underline">使用同一请求标识重试</button>}
              </div>
            )}

            <form onSubmit={submit} className="border-t border-slate-200 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-4">
              <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-100">
                <textarea value={input} disabled={agent.isLoadingConversation} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} rows={2} placeholder="问排班、规则，或描述需要调整的内容…" className="max-h-32 min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed" />
                <button type="submit" disabled={!input.trim() || busy} className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-teal-600 text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-40" aria-label="发送消息">{agent.isSending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
              </div>
              <p className="mt-2 text-center text-[10px] text-slate-400">Enter 发送 · Shift + Enter 换行</p>
            </form>
          </>
        )}
      </aside>
    </>
  )
}
