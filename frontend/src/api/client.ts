import type {
  ApiProblem,
  Day,
  Employee,
  FeasibleResult,
  RuleDefinition,
  Schedule,
  ScheduleChange,
  ScheduleOperationResult,
  ScheduleVersion,
  ShiftType,
} from '@/types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

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
  if (status === 409) return '排班版本已更新，请刷新后重试。'
  if (status === 503) return '排班服务暂时不可用，请稍后重试。'
  return '服务出现异常，请稍后重试。'
}

function statusCodeToProblem(status: number) {
  if (status === 404) return 'entity_not_found'
  if (status === 409) return 'version_conflict'
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
}

export interface ReplanRequest {
  base_schedule_id: string
  base_version: number
  changes: ScheduleChange[]
  minimize_changes: boolean
  prompt?: string
}

export interface EmployeePatch {
  available_days?: Day[]
  leave_days?: Day[]
  preferred_shift?: ShiftType | null
}

export const api = {
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
    async list() {
      const payload = await request<RuleDefinition[] | { rules: RuleDefinition[] }>('/api/rules')
      return unwrapArray(payload, 'rules')
    },
  },

  schedules: {
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
    confirm(scheduleId: string, version: number) {
      return request<ScheduleOperationResult>('/api/schedule/confirm', {
        method: 'POST',
        body: { schedule_id: scheduleId, version },
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
    async latest(status: 'confirmed' | 'draft' = 'confirmed') {
      return request<Schedule | null>(`/api/schedules/latest?status=${status}`)
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
  },
}

export function apiErrorMessage(error: unknown): { code: string; message: string } {
  if (error instanceof ApiError) return error.problem
  if (error instanceof TypeError) {
    return { code: 'network_error', message: '无法连接排班服务，请确认服务已启动。' }
  }
  return { code: 'unknown', message: error instanceof Error ? error.message : '发生未知错误。' }
}
