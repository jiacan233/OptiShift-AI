import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, apiErrorMessage } from '@/api/client'
import { useAppStore } from '@/store/AppStore'
import type {
  AgentMessage,
  AgentToolCall,
  AgentTurnResult,
  ApiProblem,
  ConversationSummary,
  InfeasibleResult,
  TrustedAgentAction,
} from '@/types'

const WORKSPACE_STORAGE_KEY = 'optishift_browser_workspace_id'
const CONVERSATION_STORAGE_KEY = 'optishift_conversation_id'

interface PendingMessage {
  clientMessageId: string
  content: string
  trustedAction?: TrustedAgentAction
}

interface LoadConversationOptions {
  allowWhileSending?: boolean
  syncScheduleWeek?: boolean
  restoreWorkbenchResult?: boolean
}

interface AgentStoreValue {
  browserWorkspaceId: string
  conversationId: string | null
  conversationTitle: string | null
  conversations: ConversationSummary[]
  messages: AgentMessage[]
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

function persistedTurn(problem: ApiProblem): AgentTurnResult | null {
  const details = problem.details
  if (!details || typeof details !== 'object') return null
  const candidate = details as Partial<AgentTurnResult>
  return candidate.user_message && candidate.assistant_message && Array.isArray(candidate.tool_calls)
    ? candidate as AgentTurnResult
    : null
}

function latestInfeasibleMutation(messages: AgentMessage[], targetWeek: string): InfeasibleResult | null {
  for (const message of [...messages].reverse()) {
    if (
      message.role !== 'assistant'
      || message.target_week !== targetWeek
      || !message.mutation_requested
      || !['generate', 'replan'].includes(message.intent ?? '')
    ) continue

    const result = message.metadata_json?.infeasible_result
    return result?.status === 'infeasible' ? result : null
  }
  return null
}

export function AgentStoreProvider({ children }: { children: ReactNode }) {
  const scheduleStore = useAppStore()
  const [browserWorkspaceId] = useState(loadWorkspaceId)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [conversationTitle, setConversationTitle] = useState<string | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [tracesByMessage, setTracesByMessage] = useState<Record<string, AgentToolCall[]>>({})
  const [isChatOpen, setChatOpen] = useState(false)
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

  const rememberConversation = useCallback((id: string) => {
    conversationIdRef.current = id
    setConversationId(id)
    localStorage.setItem(CONVERSATION_STORAGE_KEY, id)
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
      setPendingMessage(null)
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
      restoreWorkbenchResult = true,
    } = options
    if (isSending && !allowWhileSending) return
    const requestId = loadRequestRef.current + 1
    loadRequestRef.current = requestId
    setLoadingConversation(true)
    setAgentError(null)
    try {
      const detail = await api.agent.getConversation(id, browserWorkspaceId)
      if (requestId !== loadRequestRef.current) return
      rememberConversation(id)
      setConversationTitle(detail.conversation.title)
      setMessages(detail.messages)
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
        if (restoreWorkbenchResult) {
          const infeasible = latestInfeasibleMutation(detail.messages, targetWeek)
          if (infeasible) await scheduleStore.applyScheduleResult(infeasible)
        }
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
    const savedConversationId = localStorage.getItem(CONVERSATION_STORAGE_KEY)
    void (async () => {
      try {
        if (savedConversationId) await loadConversation(savedConversationId)
        else await createConversation()
        await refreshHistory()
      } catch (error) {
        if (['entity_not_found', 'conversation_not_found'].includes(apiErrorMessage(error).code)) {
          localStorage.removeItem(CONVERSATION_STORAGE_KEY)
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

  const executeMessage = useCallback(async (request: PendingMessage) => {
    if (sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setAgentError(null)
    setPendingMessage(request)
    try {
      const id = await ensureConversation()
      const turn = await api.agent.sendMessage(id, {
        browser_workspace_id: browserWorkspaceId,
        client_message_id: request.clientMessageId,
        content: request.content,
        current_week_start: scheduleStore.activeWeekStart,
        trusted_action: request.trustedAction,
      })
      setMessages((current) => {
        const returned = [turn.user_message, turn.assistant_message]
        const known = new Set(current.map((message) => message.message_id))
        return [...current, ...returned.filter((message) => !known.has(message.message_id))]
      })
      setTracesByMessage((current) => ({ ...current, [turn.assistant_message.message_id]: turn.tool_calls }))
      setConversationTitle((current) => current ?? turn.user_message.content.slice(0, 28))
      if (turn.schedule_result) {
        const isStoredSchedule = turn.schedule_result.status === 'feasible' || turn.schedule_result.status === 'confirmed'
        if (!isStoredSchedule && turn.context.target_week !== scheduleStore.activeWeekStart) {
          await scheduleStore.setActiveWeek(turn.context.target_week)
        }
        await scheduleStore.applyScheduleResult(turn.schedule_result)
      } else if (turn.context.target_week && turn.context.target_week !== scheduleStore.activeWeekStart) {
        await scheduleStore.setActiveWeek(turn.context.target_week)
      }
      setPendingMessage(null)
      await loadConversation(id, {
        allowWhileSending: true,
        syncScheduleWeek: false,
        restoreWorkbenchResult: false,
      }).catch(() => undefined)
      await refreshHistory().catch(() => undefined)
    } catch (error) {
      const problem = apiErrorMessage(error)
      const turn = persistedTurn(problem)
      if (turn) {
        setMessages((current) => {
          const known = new Set(current.map((message) => message.message_id))
          return [...current, ...[turn.user_message, turn.assistant_message].filter((message) => !known.has(message.message_id))]
        })
        setTracesByMessage((current) => ({ ...current, [turn.assistant_message.message_id]: turn.tool_calls }))
        setConversationTitle((current) => current ?? turn.user_message.content.slice(0, 28))
        const activeConversationId = conversationIdRef.current
        if (activeConversationId) await loadConversation(activeConversationId, {
          allowWhileSending: true,
          syncScheduleWeek: false,
          restoreWorkbenchResult: false,
        }).catch(() => undefined)
        await refreshHistory().catch(() => undefined)
      }
      if (['draft_pending', 'version_conflict'].includes(problem.code)) {
        const refreshWeek = turn?.assistant_message.target_week ?? scheduleStore.activeWeekStart
        await scheduleStore.setActiveWeek(refreshWeek)
      }
      setAgentError(problem)
      if (!['network_error', 'message_processing', 'conversation_busy'].includes(problem.code)) setPendingMessage(null)
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }, [browserWorkspaceId, ensureConversation, loadConversation, refreshHistory, scheduleStore])

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
      setHistoryOpen(false)
      await refreshHistory().catch(() => undefined)
    } catch (error) {
      setAgentError(apiErrorMessage(error))
    }
  }, [createConversation, isSending, refreshHistory])

  const value = useMemo<AgentStoreValue>(() => ({
    browserWorkspaceId,
    conversationId,
    conversationTitle,
    conversations,
    messages,
    tracesByMessage,
    isChatOpen,
    isHistoryOpen,
    isSending,
    isLoadingConversation,
    agentError,
    pendingMessage,
    openChat: () => setChatOpen(true),
    closeChat: () => setChatOpen(false),
    showHistory: async () => {
      setHistoryOpen(true)
      await refreshHistory().catch((error) => setAgentError(apiErrorMessage(error)))
    },
    hideHistory: () => setHistoryOpen(false),
    newConversation,
    loadConversation,
    sendMessage,
    openWithPrompt: async (content, trustedAction) => {
      setChatOpen(true)
      await sendMessage(content, trustedAction)
    },
    retryPendingMessage: async () => {
      if (pendingMessage) await executeMessage(pendingMessage)
    },
    dismissError: () => setAgentError(null),
  }), [agentError, browserWorkspaceId, conversationId, conversationTitle, conversations, executeMessage, isChatOpen, isHistoryOpen, isLoadingConversation, isSending, loadConversation, messages, newConversation, pendingMessage, refreshHistory, sendMessage, tracesByMessage])

  return <AgentStore.Provider value={value}>{children}</AgentStore.Provider>
}

// The provider and its hook intentionally share this module as one store boundary.
// eslint-disable-next-line react-refresh/only-export-components
export function useAgentStore() {
  const value = useContext(AgentStore)
  if (!value) throw new Error('useAgentStore must be used within AgentStoreProvider')
  return value
}
