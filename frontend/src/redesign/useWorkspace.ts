import { useMemo } from 'react'
import { useAppStore } from '@/store/AppStore'
import { DAY_LABELS, roleLabel, SHIFT_LABELS } from '@/lib/presentation'
import { DAYS } from '@/types'
import type { EmployeeRow, RoleType, SkillType } from './types/schedule'

export const SKILLS: Record<string, SkillType> = {
  manager: '店长值守',
  beverage: '饮品制作',
  cashier: '收银',
  inventory: '库存管理',
}

interface EmployeeRosterEntry {
  name: string
  role: RoleType
  avatar: string
  preferredShift?: 'morning' | 'evening' | 'none'
}

export const EMPLOYEE_ROSTER: Record<string, EmployeeRosterEntry> = {
  E01: {
    name: '林逸 (E01)',
    role: '店长',
    avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E02: {
    name: '张宇 (E02)',
    role: '副店长',
    avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E03: {
    name: '陈思琪 (E03)',
    role: '值班主管',
    avatar: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E04: {
    name: '赵子轩 (E04)',
    role: '值班主管',
    avatar: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E05: {
    name: '孙静 (E05)',
    role: '高级店员',
    avatar: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E06: {
    name: '李默 (E06)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E07: {
    name: '王小雨 (E07)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E08: {
    name: '周凯 (E08)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E09: {
    name: '吴晓楠 (E09)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E10: {
    name: '刘畅 (E10)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E11: {
    name: '钱佳 (E11)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E12: {
    name: '何明 (E12)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1463453091185-61582044d556?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E13: {
    name: '兼职小苏 (E13)',
    role: '兼职',
    avatar: 'https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
  E14: {
    name: '兼职阿豪 (E14)',
    role: '兼职',
    avatar: 'https://images.unsplash.com/photo-1501196354995-cbb51c65aaea?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E15: {
    name: '兼职美美 (E15)',
    role: '兼职',
    avatar: 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E16: {
    name: '兼职小锋 (E16)',
    role: '兼职',
    avatar: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E17: {
    name: '郑涛 (E17)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1508214751196-bcfd4ca60f91?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E18: {
    name: '冯婷 (E18)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1548142813-c348350df52b?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'evening',
  },
  E19: {
    name: '兼职乐乐 (E19)',
    role: '兼职',
    avatar: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'none',
  },
  E20: {
    name: '白雪 (E20)',
    role: '店员',
    avatar: 'https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=150&auto=format&fit=crop&q=80',
    preferredShift: 'morning',
  },
}

export function createFallbackAvatar(name: string, id: string) {
  const clean = name.replace(/\s*\([^)]*\)/g, '').trim() || id
  const initials = clean.slice(0, 2)
  return `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
      <defs>
        <linearGradient id="grad-${id}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#3B82F6"/>
          <stop offset="100%" stop-color="#1D4ED8"/>
        </linearGradient>
      </defs>
      <rect width="120" height="120" rx="36" fill="url(#grad-${id})"/>
      <text x="60" y="68" text-anchor="middle" fill="#ffffff" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="34" font-weight="700">${initials}</text>
    </svg>
  `.trim())}`
}

export function useWorkspace() {
  const { employees, activeSchedule, activeWeekStart, ruleConfig, result } = useAppStore()
  const effectiveRules = result?.rule_config ?? ruleConfig

  return useMemo(() => {
    const days = DAYS.map((day, index) => {
      const date = new Date(`${activeWeekStart}T00:00:00Z`)
      date.setUTCDate(date.getUTCDate() + index)
      return {
        day,
        dayCn: DAY_LABELS[day],
        date: date.getUTCDate(),
        fullDate: date.toISOString().slice(0, 10),
      }
    })

    const rows: EmployeeRow[] = employees.map((employee) => {
      const assignments = activeSchedule?.assignments.filter((a) => a.employee_id === employee.id) ?? []
      const roster = EMPLOYEE_ROSTER[employee.id]
      const displayName = roster?.name ?? `员工${employee.id.replace(/\D/g, '') || employee.id} (${employee.id})`
      const displayRole: RoleType = roster?.role ?? (roleLabel(employee.role) as RoleType)
      const avatarUrl = roster?.avatar || createFallbackAvatar(displayName, employee.id)

      return {
        employee: {
          id: employee.id,
          name: displayName,
          role: displayRole,
          avatar: avatarUrl,
          skills: employee.skills
            .map((skill) => SKILLS[skill])
            .filter((skill): skill is SkillType => Boolean(skill)),
          availableDays: employee.available_days,
          leaveDays: employee.leave_days,
          preferredShift: (employee.preferred_shift ?? roster?.preferredShift ?? 'none') as 'morning' | 'evening' | 'none',
          maxHoursPerWeek: effectiveRules.max_shifts_per_week * 8,
          currentHours: assignments.length * 8,
        },
        shifts: days.map((day) => {
          const assigned = assignments.filter((a) => a.day === day.day)
          const isLeave = employee.leave_days.includes(day.day)
          const isAvailable = employee.available_days.includes(day.day)

          if (assigned.length > 1) {
            return {
              id: `${employee.id}-${day.fullDate}`,
              day: day.day,
              date: day.date,
              shiftType: assigned[0].shift,
              timeRange: '09:00 - 21:00\n双班·例外',
            }
          }

          if (assigned.length === 1) {
            const shift = assigned[0].shift
            const timeStr = shift === 'morning' ? '09:00 - 17:00' : '13:00 - 21:00'
            const hasManager =
              employee.skills.includes('manager') ||
              employee.role === 'manager' ||
              employee.role === 'vice_manager' ||
              employee.role === 'shift_leader' ||
              displayRole === '店长' ||
              displayRole === '副店长' ||
              displayRole === '值班主管'
            const qualStr = hasManager ? '·值守' : ''
            const shiftLabel = `${SHIFT_LABELS[shift]}${qualStr}`

            return {
              id: `${employee.id}-${day.fullDate}`,
              day: day.day,
              date: day.date,
              shiftType: shift,
              timeRange: `${timeStr}\n${shiftLabel}`,
            }
          }

          if (isLeave) {
            return {
              id: `${employee.id}-${day.fullDate}`,
              day: day.day,
              date: day.date,
              shiftType: 'leave',
              timeRange: '请假 (R-08)',
            }
          }

          return {
            id: `${employee.id}-${day.fullDate}`,
            day: day.day,
            date: day.date,
            shiftType: 'off',
            timeRange: isAvailable ? 'Off' : '限制·Off',
          }
        }),
      }
    })

    return { days, rows, employees: rows.map((row) => row.employee) }
  }, [employees, activeSchedule, activeWeekStart, effectiveRules])
}
