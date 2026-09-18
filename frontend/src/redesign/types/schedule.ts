export type ShiftType = 'morning' | 'evening' | 'off' | 'leave'

export type RoleType = string

export type SkillType = '店长值守' | '饮品制作' | '收银' | '库存管理'

export interface ShiftItem {
  id: string
  day: string
  date: number
  shiftType: ShiftType
  timeRange: string
  isDragging?: boolean
  isGhost?: boolean
}

export interface Employee {
  id: string              // E01 ~ E20
  name: string
  role: RoleType
  avatar: string
  skills: SkillType[]
  availableDays: string[]  // ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  leaveDays: string[]      // e.g. ['Wed']
  preferredShift: 'morning' | 'evening' | 'none'
  maxHoursPerWeek: number  // 40
  currentHours: number     // e.g. 32
}

export interface EmployeeRow {
  employee: Employee
  shifts: ShiftItem[]
}

export interface RuleItem {
  id: string               // R-01 ~ R-09
  name: string
  group: 'personnel' | 'work_rest' | 'availability'
  groupName: string
  category: 'qualification' | 'headcount' | 'compliance' | 'data_integrity'
  type: 'hard' | 'soft'
  description: string
  threshold: string
  status: 'passed' | 'warning' | 'failed'
  scope: string
  impactText?: string
  detailedDescription?: string
  warningText?: string
  currentWeekSummary?: string
  affectedEmployees?: { id: string; name: string; detail: string }[]
}

export interface ActivityItem {
  id: string
  name: string
  avatar: string
  action: string
  time: string
}

export interface ConflictItem {
  ruleId: string
  ruleName: string
  timeSlot: string
  shortageText: string
  blockedCandidates: {
    employeeId: string
    name: string
    reason: string
    violatedRule: string
  }[]
}

export interface ChatMessage {
  id: string
  sender: 'user' | 'agent'
  content: string
  timestamp: string
  intent?: 'generate' | 'replan' | 'advice' | 'validate'
  reasoning?: {
    intentTitle: string
    constraintsChecked: string[]
    logicExplanation: string[]
    affectedCount?: number
    solverPassed: boolean
  }
}

export interface RuleViolationIssue {
  ruleId: string       // 'R-01' ~ 'R-04'
  ruleName: string
  severity: 'error' | 'warning'
  message: string
  current: number
  required: number
}

export interface ShiftCoverage {
  shiftType: ShiftType
  shiftName: string    // '早班' | '晚班'
  timeRange: string    // '09:00 - 17:00' | '13:00 - 21:00'
  assignedCount: number
  requiredCount: number
  gapCount: number     // Math.max(0, requiredCount - assignedCount)
  employees: Employee[]
  ruleIssues: RuleViolationIssue[]
  isCompliant: boolean
  managerCount: number
  baristaCount: number
  cashierCount: number
}

export interface DayCoverage {
  day: string          // 'Mon'
  dayCn: string        // '周一'
  date: number         // 5
  fullDate: string     // '2026-10-05'
  isWeekend: boolean
  totalEmployees: number
  totalHours: number
  status: 'normal' | 'shortage' | 'conflict'
  statusText: string   // '✓ 覆盖正常' | '⚠ 1 个待解决缺口' | '⚠ 规则冲突'
  conflictCount: number
  shifts: ShiftCoverage[]
}

export type ViewMode = 'employee' | 'date'
