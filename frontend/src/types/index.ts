export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const SHIFTS = ['morning', 'evening'] as const

export type Day = (typeof DAYS)[number]
export type ShiftType = (typeof SHIFTS)[number]
export type ScheduleStatus = 'draft' | 'confirmed' | 'cancelled'
export type ComplianceStatus = 'compliant' | 'authorized_violations' | 'invalid'
export type ViolationClassification = 'SATISFIED' | 'VIOLATED_AUTHORIZED' | 'VIOLATED_UNAUTHORIZED' | 'PROTECTED_RULE_VIOLATION' | 'INTEGRITY_VIOLATION'

export interface OverrideScope {
  rule_id: 'R01' | 'R02' | 'R03' | 'R04' | 'R08'
  day: Day
  shift: ShiftType
  employee_id?: string | null
  allowed_shortage?: number | null
}

export interface Violation {
  violation_id: string
  rule_id: string
  rule_name: string
  category: ViolationClassification
  day?: Day | null
  shift?: ShiftType | null
  employee_id?: string | null
  expected?: number | string | null
  actual?: number | string | null
  shortage?: number | null
  excess?: number | null
  message: string
  authorized: boolean
  authorization_id?: string | null
  authorization_source?: string | null
  constraint_id: string
}

export interface CoverageCheck {
  rule_id: string
  day: Day
  shift: ShiftType
  expected: number
  actual: number
  passed: boolean
}
export type RunAction = 'generate' | 'leave' | 'freeform'
export type PageId = 'schedule' | 'employees' | 'rules'
export type ScheduleView = 'shift' | 'employee'
export type AgentIntent = 'generate' | 'replan' | 'validate' | 'advice' | 'explain' | 'ask' | 'clarification' | 'out_of_scope' | 'what_if'

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
  classification?: ViolationClassification
}

export interface ValidationResult {
  passed: boolean
  employee_data_stale?: boolean
  rules_data_stale?: boolean
  valid?: boolean
  confirmable?: boolean
  compliance_status?: ComplianceStatus
  violations?: Violation[]
  authorized_violations?: Violation[]
  unauthorized_violations?: Violation[]
  protected_violations?: Violation[]
  integrity_violations?: Violation[]
  coverage?: CoverageCheck[]
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

export interface InfeasibleDiagnosis {
  summary?: string
  diagnostic_status?: string
  capacity_conflicts?: Conflict[]
  diagnostic_conflicts?: unknown[]
  [key: string]: unknown
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
  compliance_status?: ComplianceStatus
  authorized_violation_count?: number
  violations?: Violation[]
}

export interface FeasibleResult {
  rule_config?: import('@/api/client').RuleConfig
  status: 'feasible' | 'confirmed'
  schedule_id: string
  version: number
  schedule_status: ScheduleStatus
  schedule: Schedule
  validation: ValidationResult
  solver_status?: string
  lifecycle_status?: ScheduleStatus
  compliance_status?: ComplianceStatus
  confirmable?: boolean
  violations?: Violation[]
  diff?: ScheduleDiff | null
  impact?: ImpactRadius | null
  metrics: ScheduleMetrics
  warnings?: string[]
  explanation?: string | {
    text: string
    source: 'deterministic_template' | 'llm_polished'
    llm_fallback: boolean
    fallback_reason?: string
  } | null
}

export interface InfeasibleResult {
  status: 'infeasible' | 'scenario_preview'
  conflicts: Conflict[]
  blocking_candidates?: BlockingCandidate[]
  diagnosis?: InfeasibleDiagnosis | null
  generated_valid_schedule?: false
  message?: string
  strict_feasible?: boolean
  scenario_revision?: number
  target_week?: string
  preview_schedule?: Schedule | null
  coverage_gaps?: Conflict[]
  scenario_patches?: unknown[]
  suggestions?: Array<Record<string, unknown>>
}

export interface ScenarioPreviewResult extends InfeasibleResult {
  status: 'scenario_preview'
  strict_feasible: boolean
  scenario_revision: number
  target_week: string
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

export type ScheduleOperationResult = FeasibleResult | InfeasibleResult | ScenarioPreviewResult | ClarificationResult | EntityNotFoundResult | SolverUnknownResult

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

export interface ScheduleWeekSummary {
  week_start: string
  schedule_id?: string | null
  version?: number | null
  status?: ScheduleStatus | 'not_generated' | null
}

export interface ScheduleWeekContext {
  week_start: string
  confirmed_schedule: Schedule | null
  draft_schedule: Schedule | null
  display_schedule: Schedule | null
  versions: ScheduleVersion[]
  result?: FeasibleResult | null
}

export interface ConversationSummary {
  conversation_id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
  last_message_preview: string | null
  target_week?: string | null
}

export interface AgentSuggestion {
  id?: string
  suggestion_id: string
  title?: string
  content?: string
  description?: string
  target_week?: string | null
  proposed_changes?: ScheduleChange[]
  based_on_schedule_id?: string | null
  based_on_version?: number | null
  action?: 'generate' | 'replan'
}

export interface AgentMessage {
  message_id: string
  conversation_id: string
  client_message_id?: string | null
  role: 'user' | 'assistant'
  content: string
  intent?: AgentIntent | null
  mutation_requested?: boolean
  target_week?: string | null
  referenced_schedule_id?: string | null
  referenced_version?: number | null
  metadata_json?: {
    execution_events?: AgentExecutionEvent[]
    suggestions?: AgentSuggestion[]
    generated_draft_id?: string
    generated_draft_version?: number
    infeasible_result?: InfeasibleResult
    scenario_preview?: ScenarioPreviewResult
    [key: string]: unknown
  }
  created_at: string
}

export interface ConversationRecord {
  conversation_id: string
  browser_workspace_id: string
  title: string | null
  summary?: string | null
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
}

export interface ConversationDetail {
  conversation: ConversationRecord
  messages: AgentMessage[]
  tool_calls?: AgentToolCall[]
}

export interface AgentToolCall {
  tool_call_id: string
  conversation_id?: string
  message_id?: string | null
  tool_name: string
  input_json?: Record<string, unknown>
  output_json?: Record<string, unknown> | null
  output_summary?: string | null
  status: string
  created_at?: string
  finished_at?: string | null
}

export interface AgentTurnContext {
  target_week: string
  iso_year: number
  iso_week: number
  display_schedule_id: string | null
  display_schedule_version: number | null
  confirmed_schedule_id: string | null
  confirmed_schedule_version: number | null
}

export interface TrustedAgentAction {
  intent: Extract<AgentIntent, 'generate' | 'replan' | 'validate' | 'advice'>
  target_week?: string
  changes?: ScheduleChange[]
  minimize_changes?: boolean
  override_requested?: boolean
  force_generate?: boolean
  requested_overrides?: OverrideScope[]
  forced_assignments?: Assignment[]
  authorization_reason?: string
}

export interface AgentTurnResult {
  execution_events?: AgentExecutionEvent[]
  user_message: AgentMessage
  assistant_message: AgentMessage
  intent: AgentIntent
  mutation_requested: boolean
  context: AgentTurnContext | null
  tool_calls: AgentToolCall[]
  schedule_result: ScheduleOperationResult | null
}

export interface AgentExecutionEvent {
  event_id: string
  operation_id: string
  turn_id: string
  client_message_id: string
  stage: string
  status: 'started' | 'completed' | 'failed'
  label: string
  timestamp: string
  duration_ms: number | null
  details: {
    intent?: string
    target_week?: string
    employees?: string[]
    changes?: Array<{ employee_id: string; type: string; day: string }>
    error_type?: string
    latency_ms?: number
  }
}
