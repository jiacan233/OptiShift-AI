import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, apiErrorMessage } from '@/api/client'
import { useAppStore } from '@/store/AppStore'
import type {
  AgentExecutionEvent,
  AgentMessage,
  AgentToolCall,
  AgentTurnResult,
  ApiProblem,
  ConversationSummary,
  TrustedAgentAction,
} from '@/types'

const WORKSPACE_STORAGE_KEY = 'optishift_browser_workspace_id'
const CONVERSATION_STORAGE_KEY = 'optishift_conversation_id'
const AGENT_PANEL_OPEN_STORAGE_KEY = 'optishift_agent_panel_open'
const CONVERSATION_SESSION_STORAGE_KEY = 'optishift_conversation_id_session'

interface PendingMessage {
  clientMessageId: string
  content: string
  trustedAction?: TrustedAgentAction
}

interface LoadConversationOptions {
  allowWhileSending?: boolean
  syncScheduleWeek?: boolean
}

interface AgentStoreValue {
  browserWorkspaceId: string
  conversationId: string | null
  conversationTitle: string | null
  conversations: ConversationSummary[]
  messages: AgentMessage[]
  executionEvents: AgentExecutionEvent[]
  tracesByMessage: Record<string, AgentToolCall[]>
  isChatOpen: boolean
  isHistoryOpen: boolean
  isSending: boolean
  isLoadingConversation: boolean
  agentError: ApiProblem | null
  pendingMessage: PendingMessage | null
  openChat(): void
  closeChat(): void
  showHistory(): Promise<void>
  hideHistory(): void
  newConversation(): Promise<void>
  clearScenario(): Promise<void>
  loadConversation(conversationId: string, options?: LoadConversationOptions): Promise<void>
  sendMessage(content: string, trustedAction?: TrustedAgentAction): Promise<void>
  openWithPrompt(content: string, trustedAction?: TrustedAgentAction): Promise<void>
  retryPendingMessage(): Promise<void>
  dismissError(): void
}

const AgentStore = createContext<AgentStoreValue | null>(null)

function randomId(prefix: string) {
  const value = typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replaceAll('-', '')
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${prefix}_${value}`
}

function loadWorkspaceId() {
  const stored = localStorage.getItem(WORKSPACE_STORAGE_KEY)
  if (stored) return stored
  const created = randomId('bw')
  localStorage.setItem(WORKSPACE_STORAGE_KEY, created)
  return created
}

function loadConversationId() {
  return localStorage.getItem(CONVERSATION_STORAGE_KEY)
    ?? sessionStorage.getItem(CONVERSATION_SESSION_STORAGE_KEY)
}

function persistedTurn(problem: ApiProblem): AgentTurnResult | null {
  const details = problem.details
  if (!details || typeof details !== 'object') return null
  const candidate = details as Partial<AgentTurnResult>
  return candidate.user_message && candidate.assistant_message && Array.isArray(candidate.tool_calls)
    ? candidate as AgentTurnResult
    : null
}

export function AgentStoreProvider({ children }: { children: ReactNode }) {
  const scheduleStore = useAppStore()
  const [browserWorkspaceId] = useState(loadWorkspaceId)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [conversationTitle, setConversationTitle] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [executionEvents, setExecutionEvents] = useState<AgentExecutionEvent[]>([])
  const [tracesByMessage, setTracesByMessage] = useState<Record<string, AgentToolCall[]>>({})
  const [isChatOpen, setChatOpen] = useState(() => localStorage.getItem(AGENT_PANEL_OPEN_STORAGE_KEY) === '1')
  const [isHistoryOpen, setHistoryOpen] = useState(false)
  const [isSending, setSending] = useState(false)
  const [isLoadingConversation, setLoadingConversation] = useState(false)
  const [agentError, setAgentError] = useState<ApiProblem | null>(null)
  const [pendingMessage, setPendingMessage] = useState<PendingMessage | null>(null)
  const initialized = useRef(false)
  const conversationIdRef = useRef<string | null>(null)
  const createPromiseRef = useRef<Promise<string> | null>(null)
  const loadRequestRef = useRef(0)
  const sendingRef = useRef(false)
  const settledMessageIdsRef = useRef(new Set<string>())

  const openChat = useCallback(() => {
    localStorage.setItem(AGENT_PANEL_OPEN_STORAGE_KEY, '1')
    setChatOpen(true)
  }, [])

  const closeChat = useCallback(() => {
    localStorage.removeItem(AGENT_PANEL_OPEN_STORAGE_KEY)
    setChatOpen(false)
  }, [])

  const rememberConversation = useCallback((id: string) => {
    conversationIdRef.current = id
    setConversationId(id)
    localStorage.setItem(CONVERSATION_STORAGE_KEY, id)
    sessionStorage.setItem(CONVERSATION_SESSION_STORAGE_KEY, id)
  }, [])

  const refreshHistory = useCallback(async () => {
    const list = await api.agent.listConversations(browserWorkspaceId)
    setConversations(list)
  }, [browserWorkspaceId])

  const createConversation = useCallback(async () => {
    if (createPromiseRef.current) return createPromiseRef.current
    const operation = api.agent.createConversation(browserWorkspaceId).then((created) => {
      rememberConversation(created.conversation_id)
      setConversationTitle(created.title ?? null)
      setMessages([])
      setTracesByMessage({})
      setExecutionEvents([])
      setPendingMessage(null)
      settledMessageIdsRef.current.clear()
      return created.conversation_id
    }).finally(() => {
      createPromiseRef.current = null
    })
    createPromiseRef.current = operation
    return operation
  }, [browserWorkspaceId, rememberConversation])

  const loadConversation = useCallback(async (id: string, options: LoadConversationOptions = {}) => {
    const {
      allowWhileSending = false,
      syncScheduleWeek = true,
    } = options
    if (isSending && !allowWhileSending) return
    const requestId = loadRequestRef.current + 1
    loadRequestRef.current = requestId
    setLoadingConversation(true)
    setAgentError(null)
    try {
      const detail = await api.agent.getConversation(id, browserWorkspaceId)
      if (requestId !== loadRequestRef.current) return
      if (syncScheduleWeek) scheduleStore.dismissInfeasibleResult()
      rememberConversation(id)
      if (detail.scenario_notices?.length) setAgentError({ code: 'scenario_expired', message: '旧试排条件已失效，请重新发起本次试排。' })
      setConversationTitle(detail.conversation.title)
      setMessages(detail.messages)
      setExecutionEvents([])
      const callsById = new Map((detail.tool_calls ?? []).map((call) => [call.tool_call_id, call]))
      const restoredTraces: Record<string, AgentToolCall[]> = {}
      detail.messages.forEach((message) => {
        const ids = Array.isArray(message.metadata_json?.tool_call_ids)
          ? message.metadata_json.tool_call_ids.filter((value): value is string => typeof value === 'string')
          : []
        const calls = ids.map((toolCallId) => callsById.get(toolCallId)).filter((call): call is AgentToolCall => Boolean(call))
        if (calls.length) restoredTraces[message.message_id] = calls
      })
      setTracesByMessage(restoredTraces)
      setHistoryOpen(false)
      const targetWeek = [...detail.messages].reverse().find((message) => message.target_week)?.target_week
      if (syncScheduleWeek && targetWeek) {
        await scheduleStore.setActiveWeek(targetWeek)
        if (requestId !== loadRequestRef.current) return

      }
    } catch (error) {
      if (requestId !== loadRequestRef.current) return
      setAgentError(apiErrorMessage(error))
      throw error
    } finally {
      if (requestId === loadRequestRef.current) setLoadingConversation(false)
    }
  }, [browserWorkspaceId, isSending, rememberConversation, scheduleStore])

  useEffect(() => {
    if (scheduleStore.isBootstrapping || initialized.current) return
    initialized.current = true
    const savedConversationId = loadConversationId()
    void (async () => {
      try {
        if (savedConversationId) await loadConversation(savedConversationId)
        else await createConversation()
        await refreshHistory()
      } catch (error) {
        if (['entity_not_found', 'conversation_not_found'].includes(apiErrorMessage(error).code)) {
          localStorage.removeItem(CONVERSATION_STORAGE_KEY)
          sessionStorage.removeItem(CONVERSATION_SESSION_STORAGE_KEY)
          setAgentError(null)
          await createConversation().catch((createError) => setAgentError(apiErrorMessage(createError)))
          await refreshHistory().catch(() => undefined)
        } else setAgentError(apiErrorMessage(error))
      }
    })()
  }, [createConversation, loadConversation, refreshHistory, scheduleStore.isBootstrapping])

  const ensureConversation = useCallback(async () => (
    conversationIdRef.current ?? createConversation()
  ), [createConversation])

  const applyTurnResult = useCallback(async (turn: AgentTurnResult, id: string) => {
    const settleKey = turn.user_message.client_message_id ?? turn.user_message.message_id
    if (settledMessageIdsRef.current.has(settleKey)) return
    settledMessageIdsRef.current.add(settleKey)
    setMessages((current) => {
      const returned = [turn.user_message, turn.assistant_message]
      const known = new Set(current.map((message) => message.message_id))
      return [...current, ...returned.filter((message) => !known.has(message.message_id))]
    })
    setTracesByMessage((current) => ({ ...current, [turn.assistant_message.message_id]: turn.tool_calls }))
    setConversationTitle((current) => current ?? turn.user_message.content.slice(0, 28))
    const targetWeek = turn.context?.target_week
    if (turn.schedule_result) {
      const isStoredSchedule = turn.schedule_result.status === 'feasible' || turn.schedule_result.status === 'confirmed'
      if (!isStoredSchedule && targetWeek && targetWeek !== scheduleStore.activeWeekStart) {
        await scheduleStore.setActiveWeek(targetWeek)
      }
      await scheduleStore.applyScheduleResult(turn.schedule_result)
    } else {
      scheduleStore.dismissInfeasibleResult()
      if (targetWeek && targetWeek !== scheduleStore.activeWeekStart) await scheduleStore.setActiveWeek(targetWeek)
    }
    setPendingMessage(null)
    setAgentError(null)
    await loadConversation(id, {
      allowWhileSending: true,
      syncScheduleWeek: false,
    }).catch(() => undefined)
    await refreshHistory().catch(() => undefined)
  }, [loadConversation, refreshHistory, scheduleStore])

  const executeMessage = useCallback(async (request: PendingMessage) => {
    if (sendingRef.current || scheduleStore.isBootstrapping || scheduleStore.isRunning || scheduleStore.isLoadingWeek || scheduleStore.isSavingEmployee) return
    sendingRef.current = true
    setSending(true)
    setAgentError(null)
    setPendingMessage(request)
    setExecutionEvents([])
    try {
      const id = await ensureConversation()
      const turn = await api.agent.streamMessage(id, {
        browser_workspace_id: browserWorkspaceId,
        client_message_id: request.clientMessageId,
        content: request.content,
        current_week_start: scheduleStore.activeWeekStart,
        trusted_action: request.trustedAction,
      }, (event) => setExecutionEvents((events) => (
        event.client_message_id !== request.clientMessageId || events.some((item) => item.event_id === event.event_id)
          ? events : [...events, event]
      )))
      await applyTurnResult(turn, id)
    } catch (error) {
      const problem = apiErrorMessage(error)
      const recoveredTurn = persistedTurn(problem)
      if (recoveredTurn) {
        const activeConversationId = conversationIdRef.current
        if (activeConversationId) await applyTurnResult(recoveredTurn, activeConversationId)
        if (!['network_error', 'message_processing', 'conversation_busy', 'agent_operation_failed', 'result_pending'].includes(problem.code)) {
          setAgentError(problem)
          setPendingMessage(null)
        }
        return
      }
      if (['draft_pending', 'version_conflict'].includes(problem.code)) {
        await scheduleStore.setActiveWeek(scheduleStore.activeWeekStart)
      }
      setAgentError(problem)
      if (!['network_error', 'message_processing', 'conversation_busy', 'agent_operation_failed', 'result_pending'].includes(problem.code)) setPendingMessage(null)
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }, [applyTurnResult, browserWorkspaceId, ensureConversation, scheduleStore])

  const sendMessage = useCallback(async (content: string, trustedAction?: TrustedAgentAction) => {
    const trimmed = content.trim()
    if (!trimmed || sendingRef.current || isLoadingConversation) return
    await executeMessage({ clientMessageId: randomId('cm'), content: trimmed, trustedAction })
  }, [executeMessage, isLoadingConversation])

  const newConversation = useCallback(async () => {
    if (isSending) return
    loadRequestRef.current += 1
    setLoadingConversation(false)
    setAgentError(null)
    try {
      await createConversation()
      scheduleStore.dismissInfeasibleResult()
      setHistoryOpen(false)
      await refreshHistory().catch(() => undefined)
    } catch (error) {
      setAgentError(apiErrorMessage(error))
    }
  }, [createConversation, isSending, refreshHistory, scheduleStore])

  const value = useMemo<AgentStoreValue>(() => ({
    browserWorkspaceId,
    conversationId,
    conversationTitle,
    conversations,
    messages,
    tracesByMessage,
    executionEvents,
    isChatOpen,
    isHistoryOpen,
    isSending,
    isLoadingConversation,
    agentError,
    pendingMessage,
    openChat,
    closeChat,
    showHistory: async () => {
      setHistoryOpen(true)
      await refreshHistory().catch((error) => setAgentError(apiErrorMessage(error)))
    },
    hideHistory: () => setHistoryOpen(false),
    newConversation,
    clearScenario: async () => {
      if (sendingRef.current || !conversationIdRef.current) return
      try {
        await api.agent.clearScenario(conversationIdRef.current, browserWorkspaceId, scheduleStore.activeWeekStart, scheduleStore.infeasibleResult?.scenario_revision)
        scheduleStore.dismissInfeasibleResult()
        setAgentError(null)
      } catch (error) {
        setAgentError(apiErrorMessage(error))
      }
    },
    loadConversation,
    sendMessage,
    openWithPrompt: async (content, trustedAction) => {
      openChat()
      await sendMessage(content, trustedAction)
    },
    retryPendingMessage: async () => {
      if (pendingMessage) await executeMessage(pendingMessage)
    },
    dismissError: () => setAgentError(null),
  }), [executionEvents, agentError, browserWorkspaceId, closeChat, conversationId, conversationTitle, conversations, executeMessage, isChatOpen, isHistoryOpen, isLoadingConversation, isSending, loadConversation, messages, newConversation, openChat, pendingMessage, refreshHistory, sendMessage, tracesByMessage, scheduleStore])

  return <AgentStore.Provider value={value}>{children}</AgentStore.Provider>
}

// The provider and its hook intentionally share this module as one store boundary.
// eslint-disable-next-line react-refresh/only-export-components
export function useAgentStore() {
  const value = useContext(AgentStore)
  if (!value) throw new Error('useAgentStore must be used within AgentStoreProvider')
  return value
}
