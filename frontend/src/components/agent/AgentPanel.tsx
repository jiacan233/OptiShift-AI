import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BarChart3, CalendarPlus, ShieldCheck, Umbrella, Activity, AlertCircle, Bot, CheckCircle2, History, LoaderCircle, MessageSquarePlus, Send, Sparkles, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import { AgentTrace } from '@/components/agent/AgentTrace'
import { ConversationHistory } from '@/components/agent/ConversationHistory'
import { MessageBubble } from '@/components/agent/MessageBubble'
import { ScenarioState } from '@/components/agent/ScenarioState'
import { api, apiErrorMessage, type LlmHealthResult } from '@/api/client'
import { errorCodeLabel, problemDetail, problemMessage } from '@/lib/presentation'
import { weekLabel } from '@/lib/isoWeek'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import type { TrustedAgentAction } from '@/types'

const QUICK_QUESTIONS: Array<{ label: string; prompt: string; icon: typeof CalendarPlus; color: string; action: TrustedAgentAction }> = [
  { label: '生成当前周排班', prompt: '帮我生成当前周排班，尽量满足员工早晚班偏好。', icon: CalendarPlus, color: 'text-blue-600', action: { intent: 'generate' } },
  { label: 'E02 周五临时请假', prompt: 'E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。', icon: Umbrella, color: 'text-amber-600', action: { intent: 'replan', changes: [{ employee_id: 'E02', type: 'leave', day: 'Fri' }], minimize_changes: true } },
  { label: '解释调度逻辑', prompt: '请解释当前周排班的调度逻辑，并分析可以优化的地方。', icon: BarChart3, color: 'text-indigo-600', action: { intent: 'advice' } },
  { label: '运行合规校验', prompt: '帮我检查当前排班有没有违反规则。', icon: ShieldCheck, color: 'text-emerald-600', action: { intent: 'validate' } },
]

export function AgentPanel() {
  const agent = useAgentStore()
  const schedule = useAppStore()
  const busy = agent.isSending || agent.isLoadingConversation || schedule.isBootstrapping || schedule.isRunning || schedule.isLoadingWeek || !!schedule.isSavingEmployee
  const [input, setInput] = useState('')
  const [llmHealth, setLlmHealth] = useState<LlmHealthResult | null>(null)
  const [llmHealthError, setLlmHealthError] = useState<string | null>(null)
  const [isCheckingLlm, setCheckingLlm] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLElement>(null)
  const { isChatOpen, closeChat } = agent

  useEffect(() => {
    if (!isChatOpen) return
    const previous = document.activeElement as HTMLElement | null
    panelRef.current?.focus({ preventScroll: true })
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [isChatOpen])

  useEffect(() => {
    if (agent.isChatOpen && !agent.isHistoryOpen) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
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
  const routerCheck = llmHealth?.checks.agent_router
  const structuredReady = llmHealth?.status === 'ok' && basicCheck?.status === 'ok' && structuredCheck?.status === 'ok' && routerCheck?.status === 'ok'

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

  return createPortal(
    <>
      <aside ref={panelRef} tabIndex={-1} data-agent-panel="open" className="copilot-overlay flex min-h-0 flex-col overflow-hidden border border-slate-200/80 bg-white outline-none" role="dialog" aria-label="OptiShift Copilot 智能排班助手" onKeyDown={event => {
        if (event.key === 'Escape') { event.stopPropagation(); closeChat() }
      }}>
        <header className="max-h-[45%] shrink-0 overflow-y-auto border-b border-slate-100 bg-slate-50/50 p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-md shadow-blue-500/20"><Sparkles className="h-5 w-5" /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-extrabold text-slate-900">OptiShift Copilot</h2><span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-blue-600">AI + CP-SAT</span></div>
              <p className="text-[11px] font-medium text-slate-400">当前上下文：{weekLabel(schedule.activeWeekStart)} · 排班工作台</p>
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
          <div className="mt-2 flex items-center gap-1.5 text-[10px] font-semibold text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${agent.agentError ? 'bg-red-400' : agent.isSending ? 'bg-amber-400' : 'bg-emerald-500'}`} />{agent.isSending ? '正在处理请求' : agent.agentError ? '请求未完成' : agent.conversationId ? '对话已同步' : '等待连接'}</div>
          {(isCheckingLlm || llmHealth || llmHealthError) && (
            <div aria-live="polite" className={`mt-2 rounded-lg border px-3 py-2 text-xs ${structuredReady ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : isCheckingLlm ? 'border-slate-200 bg-slate-50 text-slate-600' : 'border-red-200 bg-red-50 text-red-800'}`}>
              {isCheckingLlm ? (
                <span className="flex items-center gap-2"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />正在连接 AI Provider…</span>
              ) : structuredReady ? (
                <div className="flex items-start gap-2"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div><p className="font-black">AI 联通正常</p><p className="mt-0.5 text-[10px]">模型：{llmHealth?.model ?? ''}</p><p className="mt-0.5 text-[10px]">基础聊天：✓ {basicCheck?.latency_ms != null ? `${basicCheck.latency_ms} ms` : '耗时未返回'}</p><p className="mt-0.5 text-[10px]">结构化输出：✓ {structuredCheck?.latency_ms != null ? `${structuredCheck.latency_ms} ms` : '耗时未返回'}</p><p className="mt-0.5 text-[10px]">Agent Router：✓ {routerCheck?.latency_ms != null ? `${routerCheck.latency_ms} ms` : '耗时未返回'}{routerCheck?.fallback_used ? ' · 使用备用 JSON' : ''}</p></div></div>
              ) : llmHealth ? (
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div>
                  <p className="font-black">{basicCheck?.status === 'ok' ? 'AI 服务部分可用（degraded）' : 'AI 联通失败'}</p>
                  {basicCheck?.status === 'ok' && structuredCheck?.status !== 'ok' ? <p className="mt-0.5 leading-5">Agent 结构化输出不可用</p> : <p className="mt-0.5 leading-5">{routerCheck?.status === 'error' ? 'Agent Router 不可用' : basicCheck?.message || structuredCheck?.message || 'AI Provider 暂时不可用。'}</p>}
                  {structuredCheck?.status !== 'ok' && structuredCheck && <p className="mt-0.5 leading-5">{structuredCheck.provider_message || structuredCheck.message || ''}</p>}
                  {basicCheck?.status !== 'ok' && basicCheck && <p className="mt-0.5 leading-5">{basicCheck.provider_message || ''}</p>}
                  {(() => { const check = basicCheck?.status !== 'ok' ? basicCheck : structuredCheck?.status !== 'ok' ? structuredCheck : routerCheck; return <p className="mt-0.5 font-mono text-[10px]">{check?.provider_status ? `HTTP ${check.provider_status} · ` : ''}{check?.error_type || 'provider_error'}{check?.latency_ms != null ? ` · ${check.latency_ms} ms` : ''}</p> })()}
                </div></div>
              ) : (
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><div><p className="font-black">无法执行检测</p><p className="mt-0.5 leading-5">{llmHealthError}</p></div></div>
              )}
            </div>
          )}
          {!agent.isHistoryOpen && <p className="mt-3 truncate text-sm font-bold text-slate-700">{agent.conversationTitle || '新对话'}</p>}
        </header>

            {agent.agentError && (
              <div role="alert" className="mx-4 my-3 max-h-[30%] shrink-0 overflow-y-auto rounded-xl border border-red-200 bg-red-50 p-3 text-red-800 sm:mx-5">
                <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><div><p className="text-xs font-black">{errorCodeLabel(agent.agentError.code)}</p><p className="mt-0.5 text-xs leading-5">{problemMessage(agent.agentError.code, agent.agentError.message)}</p>{errorDetail && <p className="mt-1 font-mono text-[10px] text-red-600">{errorDetail}</p>}</div><button type="button" onClick={agent.dismissError} className="ml-auto" aria-label="关闭 Agent 错误"><X className="h-3.5 w-3.5" /></button></div>
                {agent.pendingMessage && <button type="button" onClick={() => void agent.retryPendingMessage()} disabled={busy} className="mt-2 text-xs font-black text-red-700 underline">使用同一请求标识重试</button>}
              </div>
            )}

        {agent.isHistoryOpen ? (
          <ConversationHistory conversations={agent.conversations} currentId={agent.conversationId} disabled={busy} onBack={agent.hideHistory} onSelect={(id) => void agent.loadConversation(id).catch(() => undefined)} />
        ) : (
          <>
            <div ref={scrollRef} className="soft-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[#F8FAFC] p-4">
              <ScenarioState scenario={agent.scenario} />
              <div className="mb-4 rounded-xl border border-emerald-100/60 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-800">
                <span className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-3.5 w-3.5 shrink-0" />确定性求解引擎 · OR-Tools CP-SAT</span>
                <p className="mt-1 text-[10px] text-emerald-700">{agent.isSending ? '正在处理请求 · 执行状态见下方进度' : schedule.result?.solver_status ? `最近求解状态：${schedule.result.solver_status}` : '执行状态将在实际请求后显示'}</p>
              </div>
              <div className="mb-4 rounded-2xl border border-slate-100 bg-white p-3">
                <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">推荐操作（点击即发送）</p>
                <div className="grid grid-cols-2 gap-1.5">
                  {QUICK_QUESTIONS.map(({ label, prompt, action, icon: Icon, color }) => {
                    const disabled = busy || (action.intent === 'generate' && !!schedule.draftSchedule) || (action.intent === 'replan' && (!!schedule.draftSchedule || !schedule.confirmedSchedule || !schedule.employees.some(employee => employee.id === 'E02')))
                    return <button key={label} type="button" disabled={disabled} onClick={() => void agent.sendMessage(prompt, { ...action, target_week: schedule.activeWeekStart })} className="flex items-center gap-1.5 rounded-xl border border-slate-200/80 p-2 text-left text-[11px] font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50/50 disabled:opacity-40 disabled:cursor-not-allowed"><Icon className={`h-3.5 w-3.5 shrink-0 ${color}`} /><span className="truncate">{label}</span></button>
                  })}
                </div>
              </div>
              {agent.isLoadingConversation ? (
                <div className="grid min-h-full place-items-center text-sm text-slate-500"><LoaderCircle className="mb-2 h-6 w-6 animate-spin text-blue-600" />正在恢复对话…</div>
              ) : agent.messages.length === 0 && !agent.pendingMessage && !agent.isSending ? (
                <div className="flex flex-col py-4">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-blue-100 text-blue-700"><Bot className="h-6 w-6" /></span>
                  <h3 className="mt-4 text-lg font-black text-ink">你好，我是排班助手</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-500">我可以帮你分析、解释和调整当前排班。排班调整只会生成草稿，请在工作台“智能排班方案”中预览草稿并确认生效。</p>

                </div>
              ) : (
                <div className="space-y-4">
                  {agent.messages.map((message) => (
                    <MessageBubble key={message.message_id} message={message} trace={agent.tracesByMessage[message.message_id] ?? []} suggestionsDisabled={busy} draftBlocked={!!schedule.draftSchedule} onViewPlan={() => { schedule.setPage('schedule'); agent.closeChat(); requestAnimationFrame(() => { const plan = document.getElementById('schedule-plans'); plan?.scrollIntoView({ behavior: 'smooth', block: 'start' }); plan?.focus({ preventScroll: true }) }) }} onApplySuggestion={(suggestion, execution) => {
                      const action: TrustedAgentAction = {
                        intent: execution === 'create_draft' ? (suggestion.action === 'replan' ? 'replan' : 'generate') : 'advice',
                        target_week: suggestion.target_week ?? schedule.activeWeekStart,
                        suggestion_id: suggestion.suggestion_id,
                        suggestion_set_id: suggestion.suggestion_set_id,
                        execution,
                      }
                      const verb = execution === 'record' ? '仅采纳' : execution === 'preview' ? '采纳并试排' : '采纳并生成草稿'
                      void agent.sendMessage(`${verb}：${suggestion.title || suggestion.description || '这条建议'}。`, action)
                    }} />
                  ))}

                </div>
              )}
              {agent.pendingMessage && !agent.messages.some((message) => message.client_message_id === agent.pendingMessage?.clientMessageId) && <div className="ml-auto mt-4 max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-blue-600 p-3 text-xs leading-relaxed text-white shadow-md shadow-blue-500/15">{agent.pendingMessage.content}</div>}
              <AgentTrace calls={[]} events={agent.executionEvents} running={agent.isSending} />
            </div>



            <form onSubmit={submit} className="shrink-0 border-t border-slate-200/80 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-4">
              <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
                <textarea value={input} disabled={agent.isLoadingConversation} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} rows={2} placeholder="问排班、规则，或描述需要调整的内容…" aria-label="排班消息" className="max-h-32 min-h-[44px] min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed" />
                <button type="submit" disabled={!input.trim() || busy} className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-blue-600 text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40" aria-label="发送消息">{agent.isSending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
              </div>
              <p className="mt-2 text-center text-[10px] text-slate-400">Enter 发送 · Shift + Enter 换行</p>
            </form>
          </>
        )}
      </aside>
    </>, document.body
  )
}
