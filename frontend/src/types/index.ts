export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const SHIFTS = ['morning', 'evening'] as const

export type Day = (typeof DAYS)[number]
export type ShiftType = (typeof SHIFTS)[number]
export type ScheduleStatus = 'draft' | 'confirmed' | 'cancelled'
export type RunAction = 'generate' | 'leave' | 'freeform'
export type PageId = 'schedule' | 'employees' | 'rules'
export type ScheduleView = 'shift' | 'employee'

export interface Employee {
  id: string
  role: string
  skills: string[]
  available_days: Day[]
  leave_days: Day[]
  preferred_shift: ShiftType | null
}

export interface Assignment {
  employee_id: string
  day: Day
  shift: ShiftType
}

export interface Schedule {
  schedule_id: string
  version: number
  parent_schedule_id: string | null
  status: ScheduleStatus
  week_start: string
  assignments: Assignment[]
  created_at: string
}

export interface RuleCheck {
  rule_id: string
  passed: boolean
  message?: string
  details?: Record<string, unknown>
}

export interface ValidationResult {
  passed: boolean
  total: number
  passed_count: number
  checks: RuleCheck[]
}

export interface ScheduleMetrics {
  preference_rate: number
  workload_gap: number
  changed_assignments: number
}

export interface ShiftDelta {
  day: Day
  shift: ShiftType
  added: string[]
  removed: string[]
  unchanged?: string[]
}

export interface ScheduleDiff {
  added: Assignment[]
  removed: Assignment[]
  unchanged: Assignment[]
  shifts: ShiftDelta[]
  changed_shifts: number
  affected_employees: string[]
  hard_violations: number
}

export interface ImpactRadius {
  direct_changes: Array<ShiftDelta | string>
  related_changes: Array<ShiftDelta | string>
  unchanged_shifts: number
  total_shifts: number
}

export interface BlockingCandidate {
  employee_id: string
  day?: Day
  shift?: ShiftType
  coverage_rule_id?: string
  reasons: Array<string | { rule_id: string; message: string; details?: Record<string, unknown> }>
}

export interface Conflict {
  rule_id: string
  day: Day
  shift: ShiftType
  required: number
  available: number
  shortage: number
  message?: string
  blocked_candidates?: BlockingCandidate[]
}

export interface ClarificationCandidate {
  employee_id: string
  role: string
  context?: string | { available_days?: Day[]; leave_days?: Day[] }
}

export interface ClarificationState {
  id: string
  prompt: string
  candidates: ClarificationCandidate[]
}

export interface RuleDefinition {
  id: string
  category: 'hard' | 'soft'
  name: string
  description: string
  enabled?: boolean
}

export interface ScheduleVersion {
  schedule_id: string
  version: number
  status: ScheduleStatus
  created_at: string
  parent_schedule_id: string | null
  base_version?: number | null
}

export interface FeasibleResult {
  status: 'feasible' | 'confirmed'
  schedule_id: string
  version: number
  schedule_status: ScheduleStatus
  schedule: Schedule
  validation: ValidationResult
  diff?: ScheduleDiff | null
  impact?: ImpactRadius | null
  metrics: ScheduleMetrics
  warnings?: string[]
  explanation?: string
}

export interface InfeasibleResult {
  status: 'infeasible'
  conflicts: Conflict[]
  blocking_candidates?: BlockingCandidate[]
  diagnosis?: Record<string, unknown>
  generated_valid_schedule?: false
  message?: string
}

export interface EntityNotFoundResult {
  status: 'entity_not_found'
  message: string
  details?: unknown
}

export interface SolverUnknownResult {
  status: 'solver_unknown'
  solver_status?: string
  message: string
}

export interface ClarificationResult {
  status: 'clarification_required'
  clarification: ClarificationState
}

export type ScheduleOperationResult = FeasibleResult | InfeasibleResult | ClarificationResult | EntityNotFoundResult | SolverUnknownResult

export interface ScheduleChange {
  employee_id: string
  type: 'leave' | 'unavailable' | 'available' | 'preference' | 'assign' | 'unassign'
  day: Day
  shift?: ShiftType
  value?: string | boolean | null
}

export interface ApiProblem {
  code: string
  message: string
  details?: unknown
  status?: number
}
