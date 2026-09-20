import type { Employee, EmployeeRow, ShiftCoverage, DayCoverage, RuleViolationIssue } from '../types/schedule'
import type { Assignment, ValidationResult } from '@/types'

export interface WeekMetrics {
  totalShifts: number
  compliantShifts: number
  coverageRate: number
  totalGaps: number
  totalHours: number
  totalLeaveEmployees: number
  activeEmployeesCount: number
  assignedEmployeesCount: number
  zeroShiftEmployeesCount: number
  alerts: {
    id: string
    title: string
    subtitle: string
    type: 'open' | 'overtime' | 'attendance' | 'rule'
    color: string
    day?: string
    shiftType?: 'morning' | 'evening'
  }[]
}

/**
 * Calculates deterministic DayCoverage for all days in daysHeader
 * from all persisted assignments, employee skills, and validation results.
 */
export function calculateDayCoverage(
  daysHeader: { day: string; dayCn: string; date: number; fullDate: string }[],
  scheduleData: EmployeeRow[],
  ruleConfig: {
    manager_per_shift?: number
    beverage_per_shift?: number
    cashier_per_shift?: number
    weekday_min_staff?: number
    weekend_min_staff?: number
  },
  assignments: Assignment[],
  validation?: ValidationResult,
): DayCoverage[] {
  const managerRequired = ruleConfig?.manager_per_shift ?? 1
  const beverageRequired = ruleConfig?.beverage_per_shift ?? 2
  const cashierRequired = ruleConfig?.cashier_per_shift ?? 1
  const weekdayMin = ruleConfig?.weekday_min_staff ?? 4
  const weekendMin = ruleConfig?.weekend_min_staff ?? 6

  return daysHeader.map((header) => {
    const isWeekend = header.day === 'Sat' || header.day === 'Sun'
    const requiredPerShift = isWeekend ? weekendMin : weekdayMin

    // Helper to evaluate a specific shift type on this day
    const evaluateShift = (shiftType: 'morning' | 'evening', shiftName: string, timeRange: string): ShiftCoverage => {
      // Find all employees assigned to this shift on this day
      const assigned: Employee[] = []
      scheduleData.forEach((row) => {
        if (assignments.some((a) => a.employee_id === row.employee.id && a.day === header.day && a.shift === shiftType)) {
          assigned.push(row.employee)
        }
      })

      const assignedCount = assigned.length
      const gapCount = Math.max(0, requiredPerShift - assignedCount)

      // Count skills based strictly on Employee Master Data (R-09 技能保真)
      const managerCount = assigned.filter((emp) => emp.skills.includes('店长值守')).length

      const baristaCount = assigned.filter((emp) => emp.skills.includes('饮品制作')).length
      const cashierCount = assigned.filter((emp) => emp.skills.includes('收银')).length

      const ruleIssues: RuleViolationIssue[] = []

      // R-01: 店长值守底线 (≥ 1人 / 班)
      if (managerCount < managerRequired) {
        ruleIssues.push({
          ruleId: 'R-01',
          ruleName: '店长值守底线',
          severity: 'error',
          message: '缺少具备店长值守资格的管理人员',
          current: managerCount,
          required: managerRequired,
        })
      }

      // R-02: 饮品制作技能 (≥ 2人 / 班)
      if (baristaCount < beverageRequired) {
        ruleIssues.push({
          ruleId: 'R-02',
          ruleName: '饮品制作技能',
          severity: 'warning',
          message: `吧台制作技能不足 (${baristaCount} / ${beverageRequired} 人)`,
          current: baristaCount,
          required: beverageRequired,
        })
      }

      // R-03: 收银技能配备 (≥ 1人 / 班)
      if (cashierCount < cashierRequired) {
        ruleIssues.push({
          ruleId: 'R-03',
          ruleName: '收银技能配备',
          severity: 'warning',
          message: '缺少具备收银与结账资质人员',
          current: cashierCount,
          required: cashierRequired,
        })
      }

      // R-04: 门店人员底线 (平日 ≥ 4人，周末 ≥ 6人)
      if (assignedCount < requiredPerShift) {
        ruleIssues.push({
          ruleId: 'R-04',
          ruleName: isWeekend ? '周末客流高峰底线' : '工作日在岗底线',
          severity: 'warning',
          message: `${isWeekend ? '周末' : '工作日'}在岗底线缺 ${gapCount} 人 (${assignedCount} / ${requiredPerShift} 人)`,
          current: assignedCount,
          required: requiredPerShift,
        })
      }

      for (const violation of validation?.violations ?? []) {
        if (violation.day !== header.day || (violation.shift && violation.shift !== shiftType)) continue
        const ruleId = violation.rule_id.replace(/^R(\d+)$/, 'R-$1')
        const existing = ruleIssues.find((issue) => issue.ruleId === ruleId)
        if (existing) {
          existing.message = `${violation.authorized ? '已授权违规：' : ''}${violation.message}`
          existing.excess = typeof violation.excess === 'number' ? violation.excess : existing.excess
          continue
        }
        ruleIssues.push({
          ruleId,
          ruleName: violation.rule_name,
          severity: 'error',
          message: `${violation.authorized ? '已授权违规：' : ''}${violation.message}`,
          current: typeof violation.actual === 'number' ? violation.actual : 0,
          required: typeof violation.expected === 'number' ? violation.expected : 0,
          excess: typeof violation.excess === 'number' ? violation.excess : undefined,
        })
      }

      return {
        shiftType,
        shiftName,
        timeRange,
        assignedCount,
        requiredCount: requiredPerShift,
        gapCount,
        employees: assigned,
        ruleIssues,
        isCompliant: ruleIssues.length === 0,
        managerCount,
        baristaCount,
        cashierCount,
        managerRequired,
        beverageRequired,
        cashierRequired,
      }
    }

    const morningShift = evaluateShift('morning', '早班', '09:00 - 17:00')
    const eveningShift = evaluateShift('evening', '晚班', '13:00 - 21:00')

    // Unique employees count on this day
    const uniqueEmployees = new Set<string>()
    morningShift.employees.forEach((e) => uniqueEmployees.add(e.id))
    eveningShift.employees.forEach((e) => uniqueEmployees.add(e.id))
    const totalEmployeesOnDay = uniqueEmployees.size

    // Total assignment hours on this day (8h per shift)
    const totalHoursOnDay = (morningShift.assignedCount + eveningShift.assignedCount) * 8

    const allIssues = [...morningShift.ruleIssues, ...eveningShift.ruleIssues]
    const dayGaps = morningShift.gapCount + eveningShift.gapCount
    const conflictCount = allIssues.length

    let status: 'normal' | 'shortage' | 'conflict' = 'normal'
    let statusText = '✓ 覆盖正常'

    // R-04 is normally a minimum-only check. It can also carry an exact or
    // maximum staffing violation; those must make the day visibly conflicted
    // even when there is no shortage.
    if (allIssues.some((i) => i.ruleId !== 'R-04') || (allIssues.length > 0 && dayGaps === 0)) {
      status = 'conflict'
      statusText = `⚠ ${conflictCount} 条规则冲突`
    } else if (dayGaps > 0) {
      status = 'shortage'
      statusText = `⚠ ${dayGaps} 个缺口`
    }

    const fullDate = header.fullDate

    return {
      day: header.day,
      dayCn: header.dayCn,
      date: header.date,
      fullDate,
      isWeekend,
      totalEmployees: totalEmployeesOnDay,
      totalHours: totalHoursOnDay,
      status,
      statusText,
      conflictCount,
      shifts: [morningShift, eveningShift],
    }
  })
}

/**
 * Calculates genuine weekly KPI metrics directly from schedule data
 * without hardcoded or fake numbers.
 */
export function calculateWeekMetrics(
  dayCoverages: DayCoverage[],
  scheduleData: EmployeeRow[]
): WeekMetrics {
  let totalShifts = 0
  let compliantShifts = 0
  let totalGaps = 0
  let totalHours = 0

  dayCoverages.forEach((day) => {
    day.shifts.forEach((shift) => {
      totalShifts++
      if (shift.isCompliant) {
        compliantShifts++
      }
      totalGaps += shift.gapCount
      totalHours += shift.assignedCount * 8
    })
  })

  const coverageRate = totalShifts > 0 ? Math.round((compliantShifts / totalShifts) * 100) : 100

  // Count employees who have approved leave this week
  const leaveEmployees = scheduleData.filter((row) =>
    row.employee.leaveDays.length > 0
  ).length

  // Count employees with actual shifts
  const assignedEmployees = scheduleData.filter((row) =>
    row.shifts.some((s) => s.shiftType === 'morning' || s.shiftType === 'evening')
  ).length

  const zeroShiftEmployees = scheduleData.length - assignedEmployees

  // Dynamic alerts grounded in real schedule data
  const alerts: WeekMetrics['alerts'] = []

  // Collect specific shift gaps
  dayCoverages.forEach((day) => {
    day.shifts.forEach((shift) => {
      if (!shift.isCompliant) {
        const issue = shift.ruleIssues[0]
        alerts.push({
          id: `alt-gap-${day.day}-${shift.shiftType}`,
          title: `${day.dayCn}${shift.shiftName} ${issue.ruleId} 规则提示`,
          subtitle: shift.ruleIssues.map((item) => item.message).join('；'),
          type: 'open',
          color: '#F59E0B',
          day: day.day,
          shiftType: shift.shiftType as 'morning' | 'evening',
        })
      }
    })
  })

  // Saturated hours alert (R-05)
  const saturatedEmps = scheduleData.filter((r) => {
    return r.employee.currentHours >= r.employee.maxHoursPerWeek
  })

  if (saturatedEmps.length > 0) {
    const limit = saturatedEmps[0]?.employee.maxHoursPerWeek || 40
    alerts.push({
      id: 'alt-r05-saturated',
      title: '工时饱和监控 (R-05)',
      subtitle: `${saturatedEmps.map((e) => e.employee.name.split(' ')[0]).slice(0, 3).join('、')} 已达 ${limit}h 饱和`,
      type: 'overtime',
      color: '#EF4444',
    })
  }

  // Approved leave alert (R-08)
  if (leaveEmployees > 0) {
    alerts.push({
      id: 'alt-r08-leave',
      title: '员工档案请假记录 (R-08)',
      subtitle: `全店 ${leaveEmployees} 名员工有请假记录，具体合规情况见规则校验`,
      type: 'attendance',
      color: '#3B82F6',
    })
  }

  return {
    totalShifts,
    compliantShifts,
    coverageRate,
    totalGaps,
    totalHours,
    totalLeaveEmployees: leaveEmployees,
    activeEmployeesCount: scheduleData.length,
    assignedEmployeesCount: assignedEmployees,
    zeroShiftEmployeesCount: zeroShiftEmployees,
    alerts,
  }
}
