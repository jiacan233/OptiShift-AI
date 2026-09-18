import React, { useState, useMemo } from 'react'
import {
  ChevronRight,
  Sun,
  Moon,
  Clock,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  UserX,
  RotateCcw,
  CalendarOff,
} from 'lucide-react'
import { Employee } from '../../types/schedule'
import {
  getCleanName,
  ROLE_ORDER,
  ROLE_BADGE_STYLES,
  DAYS_CN_MAP,
} from './employeeUtils'
import { EmployeeSkillList } from './EmployeeSkillList'

interface EmployeeTableProps {
  employees: Employee[]
  onSelectEmployee: (emp: Employee) => void
  onClearFilters: () => void
}

type SortField = 'name' | 'role' | 'hours' | 'skills'
type SortOrder = 'asc' | 'desc'

export const EmployeeTable: React.FC<EmployeeTableProps> = ({
  employees,
  onSelectEmployee,
  onClearFilters,
}) => {
  const [sortField, setSortField] = useState<SortField>('role')
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc')

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortOrder('asc')
    }
  }

  const sortedEmployees = useMemo(() => {
    const list = [...employees]
    list.sort((a, b) => {
      let comparison = 0
      if (sortField === 'name') {
        comparison = getCleanName(a.name).localeCompare(getCleanName(b.name), 'zh-CN')
      } else if (sortField === 'role') {
        const orderA = ROLE_ORDER[a.role] || 99
        const orderB = ROLE_ORDER[b.role] || 99
        comparison = orderA - orderB
      } else if (sortField === 'hours') {
        const ratioA = a.currentHours / a.maxHoursPerWeek
        const ratioB = b.currentHours / b.maxHoursPerWeek
        comparison = ratioA - ratioB
      } else if (sortField === 'skills') {
        comparison = a.skills.length - b.skills.length
      }

      return sortOrder === 'asc' ? comparison : -comparison
    })
    return list
  }, [employees, sortField, sortOrder])

  // Render sort icon helper
  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ArrowUpDown className="w-3 h-3 text-slate-300 group-hover:text-slate-500 transition" />
    }
    return sortOrder === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-blue-600" />
    ) : (
      <ArrowDown className="w-3 h-3 text-blue-600" />
    )
  }

  if (employees.length === 0) {
    return (
      <div className="bg-white rounded-3xl p-12 border border-slate-200/80 shadow-xs flex flex-col items-center justify-center text-center">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
          <UserX className="w-6 h-6" />
        </div>
        <h3 className="text-sm font-bold text-slate-800">没有找到符合当前条件的员工</h3>
        <p className="text-xs text-slate-400 mt-1 max-w-sm">
          请尝试调整或清空上方的搜索词、岗位或技能筛选条件
        </p>
        <button
          onClick={onClearFilters}
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-50 text-blue-600 hover:bg-blue-100 font-bold text-xs transition"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>清除全部筛选</span>
        </button>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-3xl border border-slate-200/80 shadow-xs overflow-hidden">
      <div className="overflow-x-auto custom-scrollbar">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50/75 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 select-none">
              {/* Employee Name & ID */}
              <th
                onClick={() => handleSort('name')}
                className="py-3 px-4 group cursor-pointer hover:text-slate-900 transition min-w-[180px]"
              >
                <div className="flex items-center gap-1.5">
                  <span>员工</span>
                  {renderSortIcon('name')}
                </div>
              </th>

              {/* Role */}
              <th
                onClick={() => handleSort('role')}
                className="py-3 px-4 group cursor-pointer hover:text-slate-900 transition min-w-[110px]"
              >
                <div className="flex items-center gap-1.5">
                  <span>岗位</span>
                  {renderSortIcon('role')}
                </div>
              </th>

              {/* Skills */}
              <th
                onClick={() => handleSort('skills')}
                className="py-3 px-4 group cursor-pointer hover:text-slate-900 transition min-w-[260px]"
              >
                <div className="flex items-center gap-1.5">
                  <span>认证技能</span>
                  {renderSortIcon('skills')}
                </div>
              </th>

              {/* Shift Preference */}
              <th className="py-3 px-4 min-w-[110px]">班次偏好</th>

              {/* Weekly Status (Anomalies highlighted) */}
              <th className="py-3 px-4 min-w-[140px]">本周状态</th>

              {/* Weekly Hours Load */}
              <th
                onClick={() => handleSort('hours')}
                className="py-3 px-4 group cursor-pointer hover:text-slate-900 transition min-w-[140px]"
              >
                <div className="flex items-center gap-1.5">
                  <span>本周工时</span>
                  {renderSortIcon('hours')}
                </div>
              </th>

              {/* Action */}
              <th className="py-3 px-4 text-right min-w-[80px]">操作</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
            {sortedEmployees.map((emp) => {
              const cleanName = getCleanName(emp.name)
              const roleBadgeStyle =
                ROLE_BADGE_STYLES[emp.role] || 'bg-slate-100 text-slate-600 border-slate-200'
              const hoursRatio = emp.currentHours / emp.maxHoursPerWeek
              const isHoursFull = emp.currentHours >= emp.maxHoursPerWeek
              const isHoursNear = !isHoursFull && emp.currentHours >= emp.maxHoursPerWeek - 8
              const hasLeave = emp.leaveDays.length > 0
              const isRestricted = emp.availableDays.length < 7

              return (
                <tr
                  key={emp.id}
                  tabIndex={0}
                  aria-label={`查看 ${emp.id} 员工档案`}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectEmployee(emp) } }}
                  onClick={() => onSelectEmployee(emp)}
                  className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                >
                  {/* 1. Employee: Avatar, Name, ID */}
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-3">
                      <img
                        src={emp.avatar}
                        alt={cleanName}
                        className="w-9 h-9 rounded-xl object-cover ring-1 ring-slate-200 group-hover:ring-blue-300 transition shrink-0"
                      />
                      <div className="min-w-0">
                        <div className="font-bold text-slate-900 text-xs flex items-center gap-1.5">
                          <span className="truncate">{cleanName}</span>
                        </div>
                        <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                          {emp.id}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* 2. Role */}
                  <td className="py-3 px-4 whitespace-nowrap">
                    <span
                      className={`inline-block text-[11px] font-bold px-2 py-0.5 rounded-lg border ${roleBadgeStyle}`}
                    >
                      {emp.role}
                    </span>
                  </td>

                  {/* 3. Skills (Display full skills with unified icons & overflow +N tooltip) */}
                  <td className="py-3 px-4">
                    <EmployeeSkillList skills={emp.skills} />
                  </td>

                  {/* 4. Shift Preference */}
                  <td className="py-3 px-4 whitespace-nowrap">
                    {emp.preferredShift === 'morning' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-sky-700 bg-sky-50 px-2 py-0.5 rounded-md border border-sky-100">
                        <Sun className="w-3 h-3 text-sky-500" />
                        <span>偏好早班</span>
                      </span>
                    ) : emp.preferredShift === 'evening' ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-100">
                        <Moon className="w-3 h-3 text-indigo-500" />
                        <span>偏好晚班</span>
                      </span>
                    ) : (
                      <span className="text-[11px] text-slate-400 font-medium">不限</span>
                    )}
                  </td>

                  {/* 5. Weekly Status (Prioritize anomalies) */}
                  <td className="py-3 px-4 whitespace-nowrap">
                    {hasLeave ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-md">
                        <CalendarOff className="w-3 h-3 text-rose-500" />
                        <span>
                          {emp.leaveDays.map((d) => DAYS_CN_MAP[d] || d).join('、')}请假
                        </span>
                      </span>
                    ) : isHoursFull ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-md">
                        <Clock className="w-3 h-3 text-amber-500" />
                        <span>工时已满</span>
                      </span>
                    ) : isHoursNear ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-700 bg-slate-100 px-2 py-0.5 rounded-md">
                        <span>接近上限</span>
                      </span>
                    ) : isRestricted ? (
                      emp.availableDays.length === 2 &&
                      emp.availableDays.includes('Sat') &&
                      emp.availableDays.includes('Sun') ? (
                        <span className="text-[11px] font-medium text-slate-500 bg-slate-50 px-2 py-0.5 rounded-md border border-slate-200/60">
                          仅周末可用
                        </span>
                      ) : (
                        <span className="text-[11px] font-medium text-slate-500 bg-slate-50 px-2 py-0.5 rounded-md border border-slate-200/60">
                          部分受限
                        </span>
                      )
                    ) : (
                      <span className="text-[11px] font-medium text-slate-400">可排班</span>
                    )}
                  </td>

                  {/* 6. Weekly Hours */}
                  <td className="py-3 px-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <div className="w-16 bg-slate-100 h-1.5 rounded-full overflow-hidden shrink-0">
                        <div
                          className={`h-full rounded-full transition-all ${
                            isHoursFull
                              ? 'bg-amber-500'
                              : isHoursNear
                              ? 'bg-blue-600'
                              : 'bg-emerald-500'
                          }`}
                          style={{ width: `${Math.min(100, hoursRatio * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs font-semibold text-slate-800">
                        {emp.currentHours}
                        <span className="text-slate-400 font-normal">/{emp.maxHoursPerWeek}h</span>
                      </span>
                    </div>
                  </td>

                  {/* 7. Action */}
                  <td className="py-3 px-4 text-right whitespace-nowrap">
                    <span className="inline-flex items-center gap-0.5 text-slate-400 group-hover:text-blue-600 text-xs font-semibold transition">
                      <span>详情</span>
                      <ChevronRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
