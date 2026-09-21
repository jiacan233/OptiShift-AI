import type {
  AgentExecutionEvent,
  AgentScenario,
  ApiProblem,
  Assignment,
  OverrideScope,
  AgentTurnResult,
  ConversationDetail,
  ConversationRecord,
  ConversationSummary,
  Day,
  Employee,
  FeasibleResult,
  RuleDefinition,
  Schedule,
  ScheduleChange,
  ScheduleOperationResult,
  ScheduleWeekContext,
  ScheduleWeekSummary,
  ScheduleVersion,
  ShiftType,
  TrustedAgentAction,
} from '@/types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
// Allow the backend's 300-second turn budget plus delivery time (LLM reads: 120s).
const AGENT_REQUEST_TIMEOUT_MS = 310_000

export class ApiError extends Error {
  problem: ApiProblem

  constructor(problem: ApiProblem) {
    super(problem.message)
    this.name = 'ApiError'
    this.problem = problem
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    signal: options.signal ?? (path.startsWith('/api/agent/') ? AbortSignal.timeout(AGENT_REQUEST_TIMEOUT_MS) : undefined),
    headers: {
      Accept: 'application/json',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const source = payload?.error ?? payload?.detail ?? payload
    const message = typeof source === 'string'
      ? source
      : source?.message ?? readableStatus(response.status)
    const code = typeof source === 'object' && source?.code
      ? source.code
      : statusCodeToProblem(response.status)
    throw new ApiError({ code, message, details: source?.details ?? source, status: response.status })
  }
  return payload as T
}

function readableStatus(status: number) {
  if (status === 400 || status === 422) return '请求内容未通过校验，请检查后重试。'
  if (status === 404) return '未找到所需的数据。'
  if (status === 409) return '当前操作与服务端状态冲突，请刷新后重试。'
  if (status === 503) return '排班服务暂时不可用，请稍后重试。'
  return '服务出现异常，请稍后重试。'
}

function statusCodeToProblem(status: number) {
  if (status === 404) return 'entity_not_found'
  if (status === 409) return 'conflict'
  if (status === 422) return 'validation_error'
  if (status === 503) return 'solver_unavailable'
  return 'internal_error'
}

function unwrapArray<T>(payload: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(payload)) return payload
  return payload[key] ?? []
}

export interface GenerateRequest {
  prompt: string
  week_start: string
  changes?: ScheduleChange[]
  weekend_min_staff?: number
  max_consecutive_days?: number
}

export interface RuleConfig {
  manager_per_shift: number
  beverage_per_shift: number
  cashier_per_shift: number
  weekday_min_staff: number
  weekend_min_staff: number
  max_shifts_per_week: number
  max_consecutive_days: number
}

export interface StaffingPreview {
  status: string
  target_week: string
  weekend_min_staff: number
  strict_feasible: boolean
  conflicts: Array<{ rule_id: string; day: Day; shift: ShiftType; shortage: number }>
  validation?: FeasibleResult['validation']
  preview_schedule?: Schedule
}

export interface ReplanRequest {
  base_schedule_id: string
  base_version: number
  changes: ScheduleChange[]
  minimize_changes: boolean
  prompt?: string
}

export interface ForceGenerateRequest {
  week_start: string
  base_schedule_id: string | null
  base_version: number | null
  client_message_id: string
  source_conversation_id?: string
  force_request: {
    requested_overrides: OverrideScope[]
    forced_assignments: Assignment[]
    authorization_reason: string
  }
}

export interface EmployeePatch {
  available_days?: Day[]
  leave_days?: Day[]
  preferred_shift?: ShiftType | null
}

export interface SendAgentMessageRequest {
  browser_workspace_id: string
  client_message_id: string
  content: string
  current_week_start?: string
  trusted_action?: TrustedAgentAction
}

export interface LlmHealthResult {
  enabled: boolean
  key_present: boolean
  model: string
  status: 'ok' | 'degraded' | 'error'
  checks: {
    basic_chat?: LlmHealthCheck
    structured_output?: LlmHealthCheck
    agent_router?: LlmHealthCheck
  }
}

export interface LlmHealthCheck {
  status: 'ok' | 'error'
  latency_ms?: number
  reply?: string
  error_type?: string
  message?: string
  provider_message?: string
  provider_status?: number
  stage?: string
  schema_name?: string
  schema_bytes?: number
  fallback_used?: boolean
}

async function checkLlmHealth(): Promise<LlmHealthResult> {
  const response = await fetch(`${API_BASE}/health/llm`, {
    headers: { Accept: 'application/json' },
  })
  const payload = await response.json().catch(() => null)

  if (payload && typeof payload === 'object' && (payload.status === 'ok' || payload.status === 'degraded' || payload.status === 'error')) {
    return payload as LlmHealthResult
  }

  throw new ApiError({
    code: statusCodeToProblem(response.status),
    message: readableStatus(response.status),
    details: payload,
    status: response.status,
  })
}

const RECOVERY_DELAYS_MS = [300, 500, 1000, 2000, 3000, 5000, 5000]
const RECOVERY_BUDGET_MS = AGENT_REQUEST_TIMEOUT_MS

function isRecoverableTurnProblem(error: unknown) {
  if (error instanceof ApiError) {
    return error.problem.code === 'message_processing' || error.problem.code === 'conversation_busy'
  }
  return error instanceof TypeError
}

async function recoverAgentMessage(
  conversationId: string, input: SendAgentMessageRequest,
): Promise<AgentTurnResult> {
  const started = Date.now()
  let delayIndex = 0
  while (Date.now() - started < RECOVERY_BUDGET_MS) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), RECOVERY_BUDGET_MS - (Date.now() - started))
    try {
      return await request<AgentTurnResult>(`/api/agent/conversations/${encodeURIComponent(conversationId)}/messages`, {
        method: 'POST',
        body: input,
        signal: controller.signal,
      })
    } catch (error) {
      if (controller.signal.aborted) break
      if (!isRecoverableTurnProblem(error)) throw error
      const delay = RECOVERY_DELAYS_MS[Math.min(delayIndex++, RECOVERY_DELAYS_MS.length - 1)]
      if (Date.now() - started + delay >= RECOVERY_BUDGET_MS) break
      await new Promise((resolve) => setTimeout(resolve, delay))
    } finally {
      clearTimeout(timeout)
    }
  }
  throw new ApiError({
    code: 'result_pending',
    message: '后台请求结果暂未恢复，可能仍在执行。请使用同一请求标识继续恢复。',
    details: { conversation_id: conversationId, client_message_id: input.client_message_id },
    status: 409,
  })
}

async function streamAgentMessage(
  conversationId: string, input: SendAgentMessageRequest,
  onEvent: (event: AgentExecutionEvent) => void,
): Promise<AgentTurnResult> {
  const response = await fetch(`${API_BASE}/api/agent/conversations/${encodeURIComponent(conversationId)}/messages/stream`, {
    method: 'POST',
    signal: AbortSignal.timeout(AGENT_REQUEST_TIMEOUT_MS),
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const problem = payload?.error ?? payload?.detail
    throw new ApiError({ code: problem?.code ?? statusCodeToProblem(response.status),
      message: problem?.message ?? readableStatus(response.status),
      details: problem?.details, status: response.status })
  }
  const reader = response.body?.getReader()
  if (!reader) return recoverAgentMessage(conversationId, input)
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      let boundary: RegExpExecArray | null
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const lines = frame.split(/\r?\n/)
        const kind = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
        if (!kind || kind === 'heartbeat') continue
        const data = JSON.parse(lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n'))
        if (kind === 'execution') onEvent(data as AgentExecutionEvent)
        else if (kind === 'result') return data as AgentTurnResult
        else if (kind === 'error') throw new ApiError(data as ApiProblem)
      }
      if (done) break
    }
  } catch (error) {
    // A successful stream without a terminal frame is transport ambiguity. Replay
    // the exact same idempotent turn; explicit server errors remain authoritative.
    if (error instanceof ApiError) throw error
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
  return recoverAgentMessage(conversationId, input)
}

export const api = {
  health: {
    checkLlm: checkLlmHealth,
  },

  employees: {
    async list() {
      const payload = await request<Employee[] | { employees: Employee[] }>('/api/employees')
      return unwrapArray(payload, 'employees')
    },
    update(employeeId: string, patch: EmployeePatch) {
      return request<Employee>(`/api/employees/${encodeURIComponent(employeeId)}`, {
        method: 'PATCH',
        body: patch,
      })
    },
  },

  rules: {
    configuration() {
      return request<{ rules: RuleDefinition[]; config: RuleConfig }>('/api/rules')
    },
    async list() {
      const payload = await request<RuleDefinition[] | { rules: RuleDefinition[] }>('/api/rules')
      return unwrapArray(payload, 'rules')
    },
  },

  schedules: {
    previewStaffing(weekStart: string, weekendMinStaff: number, maxConsecutiveDays?: number) {
      return request<StaffingPreview>('/api/schedule/staffing-preview', { method: 'POST', body: { week_start: weekStart, weekend_min_staff: weekendMinStaff, max_consecutive_days: maxConsecutiveDays } })
    },
    forceGenerate(input: ForceGenerateRequest) {
      return request<ScheduleOperationResult>('/api/schedule/force', { method: 'POST', body: input })
    },
    generate(input: GenerateRequest) {
      return request<ScheduleOperationResult>('/api/schedule/generate', { method: 'POST', body: input })
    },
    replan(input: ReplanRequest) {
      return request<ScheduleOperationResult>('/api/schedule/replan', { method: 'POST', body: input })
    },
    validate(scheduleId: string, version: number) {
      return request<FeasibleResult>('/api/schedule/validate', {
        method: 'POST',
        body: { schedule_id: scheduleId, version },
      })
    },
    confirm(scheduleId: string, version: number, weekStart: string) {
      return request<ScheduleOperationResult>('/api/schedule/confirm', {
        method: 'POST',
        body: { schedule_id: scheduleId, version, week_start: weekStart },
      })
    },
    cancel(scheduleId: string, version: number) {
      return request<{ status: 'cancelled'; schedule?: Schedule }>('/api/schedule/cancel', {
        method: 'POST',
        body: { schedule_id: scheduleId, version },
      })
    },
    get(scheduleId: string) {
      return request<Schedule>(`/api/schedules/${encodeURIComponent(scheduleId)}`)
    },
    async latest(status: 'confirmed' | 'draft' = 'confirmed', weekStart?: string) {
      const params = new URLSearchParams({ status })
      if (weekStart) params.set('week_start', weekStart)
      return request<Schedule | null>(`/api/schedules/latest?${params}`)
    },
    async versions(scheduleId: string) {
      const payload = await request<ScheduleVersion[] | { versions: ScheduleVersion[] }>(
        `/api/schedules/${encodeURIComponent(scheduleId)}/versions`,
      )
      return unwrapArray(payload, 'versions')
    },
    resolveClarification(clarificationId: string, employeeId: string) {
      return request<ScheduleOperationResult>('/api/schedule/resolve', {
        method: 'POST',
        body: { clarification_id: clarificationId, employee_id: employeeId },
      })
    },
    weekContext(weekStart: string) {
      return request<ScheduleWeekContext>(`/api/schedules/week-context?week_start=${encodeURIComponent(weekStart)}`)
    },
    async weeks(anchorWeekStart: string, radius = 6) {
      const payload = await request<ScheduleWeekSummary[] | { weeks: ScheduleWeekSummary[] }>(
        `/api/schedules/weeks?anchor_week_start=${encodeURIComponent(anchorWeekStart)}&radius=${radius}`,
      )
      return unwrapArray(payload, 'weeks')
    },
  },

  agent: {
    getScenario(conversationId: string, browserWorkspaceId: string, weekStart: string) {
      const query = new URLSearchParams({ browser_workspace_id: browserWorkspaceId, week_start: weekStart })
      return request<AgentScenario>(`/api/agent/conversations/${encodeURIComponent(conversationId)}/scenario?${query}`)
    },
    clearScenario(conversationId: string, browserWorkspaceId: string, weekStart: string, expectedRevision?: number) {
      return request(`/api/agent/conversations/${encodeURIComponent(conversationId)}/scenario`, {
        method: 'DELETE', body: { browser_workspace_id: browserWorkspaceId, week_start: weekStart, expected_revision: expectedRevision },
      })
    },
    streamMessage: streamAgentMessage,
    createConversation(browserWorkspaceId: string) {
      return request<Pick<ConversationRecord, 'conversation_id' | 'created_at'> & Partial<ConversationRecord>>('/api/agent/conversations', {
        method: 'POST',
        body: { browser_workspace_id: browserWorkspaceId },
      })
    },
    async listConversations(browserWorkspaceId: string) {
      const payload = await request<ConversationSummary[] | { conversations: ConversationSummary[] }>(
        `/api/agent/conversations?browser_workspace_id=${encodeURIComponent(browserWorkspaceId)}`,
      )
      return unwrapArray(payload, 'conversations')
    },
    getConversation(conversationId: string, browserWorkspaceId: string) {
      return request<ConversationDetail>(
        `/api/agent/conversations/${encodeURIComponent(conversationId)}?browser_workspace_id=${encodeURIComponent(browserWorkspaceId)}`,
      )
    },
    sendMessage(conversationId: string, input: SendAgentMessageRequest) {
      return request<AgentTurnResult>(`/api/agent/conversations/${encodeURIComponent(conversationId)}/messages`, {
        method: 'POST',
        body: input,
      })
    },
  },
}

export function apiErrorMessage(error: unknown): ApiProblem {
  if (error instanceof ApiError) return error.problem
  if (error instanceof TypeError) {
    return { code: 'network_error', message: '无法连接排班服务，请确认服务已启动。' }
  }
  return { code: 'unknown', message: error instanceof Error ? error.message : '发生未知错误。' }
}

export function confirmationError(error: unknown): ApiProblem {
  const problem = apiErrorMessage(error)
  console.error('draft_confirmation_failed', {
    status: problem.status, code: problem.code, detail: problem.details,
  })
  if (problem.code === 'version_conflict') return { ...problem, message: '当前正式排班已发生变化，请刷新后重新确认。' }
  if (problem.status === 404) return { ...problem, code: 'draft_not_found', message: '该草稿已失效，请重新生成排班。' }
  if (problem.status === 422) return { ...problem, message: '确认请求参数异常，请刷新后重试。' }
  if (problem.status && problem.status >= 500) return { ...problem, message: '确认失败，请稍后重试。' }
  return problem
}
