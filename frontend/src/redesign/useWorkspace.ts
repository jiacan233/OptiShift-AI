import { useMemo } from 'react'
import { useAppStore } from '@/store/AppStore'
import { DAY_LABELS, roleLabel, SHIFT_LABELS, SHIFT_TIMES } from '@/lib/presentation'
import { DAYS } from '@/types'
import type { EmployeeRow, SkillType } from './types/schedule'

export const SKILLS: Record<string, SkillType> = { manager: '店长值守', beverage: '饮品制作', cashier: '收银', inventory: '库存管理' }

export function useWorkspace() {
  const { employees, activeSchedule, activeWeekStart, ruleConfig, result } = useAppStore()
  const effectiveRules = result?.rule_config ?? ruleConfig
  return useMemo(() => {
    const days = DAYS.map((day, index) => {
      const date = new Date(`${activeWeekStart}T00:00:00Z`)
      date.setUTCDate(date.getUTCDate() + index)
      return { day, dayCn: DAY_LABELS[day], date: date.getUTCDate(), fullDate: date.toISOString().slice(0, 10) }
    })
    const rows: EmployeeRow[] = employees.map(employee => {
      const assignments = activeSchedule?.assignments.filter(a => a.employee_id === employee.id) ?? []
      const initials = employee.id.replace(/[<>&"']/g, '').slice(0, 4)
      return {
        employee: {
          id: employee.id, name: employee.id, role: roleLabel(employee.role),
          avatar: `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" rx="24" fill="#eff6ff"/><text x="40" y="46" text-anchor="middle" fill="#2563eb" font-family="sans-serif" font-size="20">${initials}</text></svg>`)}`,
          skills: employee.skills.map(skill => SKILLS[skill]).filter((skill): skill is SkillType => Boolean(skill)),
          availableDays: employee.available_days, leaveDays: employee.leave_days,
          preferredShift: employee.preferred_shift ?? 'none', maxHoursPerWeek: effectiveRules.max_shifts_per_week * 8, currentHours: assignments.length * 8,
        },
        shifts: days.map(day => {
          const assigned = assignments.filter(a => a.day === day.day)
          const type = assigned.length ? assigned[0].shift : employee.leave_days.includes(day.day) ? 'leave' : 'off'
          return { id: `${employee.id}-${day.fullDate}`, day: day.day, date: day.date, shiftType: type,
            timeRange: assigned.length > 1 ? '早班 + 晚班\n查看规则例外' : assigned.length ? `${SHIFT_LABELS[assigned[0].shift]}\n${SHIFT_TIMES[assigned[0].shift]}` : type === 'leave' ? '请假' : employee.available_days.includes(day.day) ? '休息' : '不可用' }
        }),
      }
    })
    return { days, rows, employees: rows.map(row => row.employee) }
  }, [employees, activeSchedule, activeWeekStart, effectiveRules])
}
