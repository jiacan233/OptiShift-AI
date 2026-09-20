import React, { useState, useMemo } from 'react'
import { Search, RotateCcw, Users, CalendarX } from 'lucide-react'
import { EmployeeRow, ShiftItem, RoleType, Employee } from '../../types/schedule'
import { ShiftCard } from './ShiftCard'

interface ScheduleGridProps {
  scheduleData: EmployeeRow[]
  onShiftClick: (employeeName: string, shift: ShiftItem) => void
  daysHeader: { day: string; dayCn: string; date: number; fullDate: string }[]
  onSelectEmployee?: (employee: Employee) => void
}

export const ScheduleGrid: React.FC<ScheduleGridProps> = ({
  scheduleData,
  onShiftClick,
  daysHeader,
  onSelectEmployee,
}) => {
  // Lightweight Filter States
  const [searchQuery, setSearchQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  // Mandatory requirement: Default to TRUE (show all active employees including 0-shift)
  const [showZeroShift, setShowZeroShift] = useState<boolean>(true)

  const rolesList: RoleType[] = ['店长', '副店长', '值班主管', '高级店员', '店员', '兼职']

  // Filtered rows
  const filteredRows = useMemo(() => {
    return scheduleData.filter((row) => {
      const emp = row.employee
      const assignedShifts = row.shifts.filter(
        (s) => s.shiftType === 'morning' || s.shiftType === 'evening'
      )
      const hasShifts = assignedShifts.length > 0
      const hasLeave = row.shifts.some((s) => s.shiftType === 'leave')

      // 1. Hide zero-shift toggle (if unchecked, hide employees with 0 shifts this week)
      if (!showZeroShift && !hasShifts) {
        return false
      }

      // 2. Search query filter
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase()
        const matchName = emp.name.toLowerCase().includes(q)
        const matchId = emp.id.toLowerCase().includes(q)
        const matchRole = emp.role.toLowerCase().includes(q)
        if (!matchName && !matchId && !matchRole) return false
      }

      // 3. Role filter
      if (roleFilter !== 'all' && emp.role !== roleFilter) {
        return false
      }

      // 4. Status filter
      if (statusFilter === 'scheduled' && !hasShifts) return false
      if (statusFilter === 'zero_shift' && hasShifts) return false
      if (statusFilter === 'leave' && !hasLeave) return false

      return true
    })
  }, [scheduleData, searchQuery, roleFilter, statusFilter, showZeroShift])

  const isFiltered =
    searchQuery !== '' || roleFilter !== 'all' || statusFilter !== 'all' || !showZeroShift

  const handleResetFilters = () => {
    setSearchQuery('')
    setRoleFilter('all')
    setStatusFilter('all')
    setShowZeroShift(true)
  }

  // Handle total empty state: no employee data at all
  if (!scheduleData || scheduleData.length === 0) {
    return (
      <div className="bg-white rounded-3xl p-12 border border-slate-200/80 text-center space-y-4 shadow-xs">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
          <Users className="w-6 h-6" />
        </div>
        <div>
          <h3 className="text-base font-bold text-slate-800">暂无员工数据</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            系统尚未同步员工主数据档案，请检查后端主数据状态。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Top Filter & Employee Count Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5 bg-slate-50/70 p-3 rounded-2xl border border-slate-200/60 text-xs">
        {/* Left: Employee Count Header */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="font-extrabold text-slate-900 text-sm">
              员工排班
            </span>
            <span className="font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full border border-blue-200 text-xs">
              {filteredRows.length} / {scheduleData.length} 员工
            </span>
          </div>

          {isFiltered && (
            <button
              onClick={handleResetFilters}
              className="text-[11px] text-slate-400 hover:text-slate-600 flex items-center gap-1 font-semibold transition"
            >
              <RotateCcw className="w-3 h-3" />
              <span>重置筛选</span>
            </button>
          )}
        </div>

        {/* Right: Lightweight Filters */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索员工姓名/工号/岗位..."
              className="pl-8 pr-2.5 py-1.5 bg-white border border-slate-200 rounded-xl text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 w-44"
            />
          </div>

          {/* Role Filter */}
          <select
            aria-label="筛选岗位"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="bg-white border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="all">全部岗位 ▾</option>
            {rolesList.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>

          {/* Status Filter */}
          <select
            aria-label="筛选排班状态"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-white border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="all">全部状态 ▾</option>
            <option value="scheduled">本周有班次</option>
            <option value="zero_shift">本周无班 (0班次)</option>
            <option value="leave">包含请假</option>
          </select>

          {/* Show Zero Shift Checkbox Toggle */}
          <label className="flex items-center gap-1.5 cursor-pointer select-none px-2 py-1 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition">
            <input
              type="checkbox"
              checked={showZeroShift}
              onChange={(e) => setShowZeroShift(e.target.checked)}
              className="rounded text-blue-600 focus:ring-blue-500 h-3.5 w-3.5"
            />
            <span className="text-[11px] font-semibold text-slate-600">
              显示无班员工
            </span>
          </label>
        </div>
      </div>

      {/* Filtered Empty State */}
      {filteredRows.length === 0 ? (
        <div className="bg-white rounded-3xl p-10 border border-slate-200/80 text-center space-y-3 shadow-xs">
          <CalendarX className="w-10 h-10 text-slate-300 mx-auto" />
          <div className="text-sm font-bold text-slate-700">未找到符合条件的员工</div>
          <p className="text-xs text-slate-400">
            尝试放宽搜索关键词或清除当前筛选条件。
          </p>
          <button
            onClick={handleResetFilters}
            className="px-3.5 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition"
          >
            清除全部筛选
          </button>
        </div>
      ) : (
        /* Schedule Matrix Table Container with Sticky Name Column and Sticky Date Header */
        <div className="relative overflow-x-auto overflow-y-auto max-h-[640px] custom-scrollbar rounded-2xl border border-slate-150/80 bg-white">
          <div className="min-w-[980px]">
            {/* Table Header (Sticky Top) */}
            <div className="sticky top-0 bg-white/95 backdrop-blur-md z-30 grid grid-cols-[210px_repeat(7,minmax(0,1fr))] items-center border-b border-slate-200/80 py-2.5 px-2 shadow-xs">
              {/* Sticky Left Corner Header */}
              <div className="sticky left-0 bg-white/95 backdrop-blur-md z-30 text-xs font-bold text-slate-400 pl-2">
                员工主数据 · 资质与岗位
              </div>

              {daysHeader.map((col) => (
                <div key={col.day} className="text-center">
                  <div className="text-[11px] font-semibold text-slate-400">
                    {col.day} ({col.dayCn})
                  </div>
                  <div className="text-sm font-extrabold text-slate-800">
                    {col.fullDate.slice(5).replace('-', '/')}
                  </div>
                </div>
              ))}
            </div>

            {/* Schedule Rows (Vertical Scrolling) */}
            <div className="divide-y divide-slate-100/80 p-1">
              {filteredRows.map((row) => {
                const assignedCount = row.shifts.filter(
                  (s) => s.shiftType === 'morning' || s.shiftType === 'evening'
                ).length
                const isZeroShift = assignedCount === 0

                return (
                  <div
                    key={row.employee.id}
                    className={`grid grid-cols-[210px_repeat(7,minmax(0,1fr))] items-center gap-2 group hover:bg-slate-50/70 p-1.5 transition ${
                      isZeroShift ? 'opacity-85 bg-slate-50/30' : ''
                    }`}
                  >
                    {/* Employee Info Column (Sticky Left, Clickable to open Employee Profile Drawer) */}
                    <button
                      type="button"
                      onClick={() => onSelectEmployee?.(row.employee)}
                      className="sticky left-0 bg-white group-hover:bg-[#F8FAFC] hover:bg-blue-50/70 z-20 flex items-center gap-2.5 pl-2 pr-2 py-1 shadow-[2px_0_5px_-2px_rgba(0,0,0,0.06)] cursor-pointer select-none transition-colors group/empCard text-left"
                      title={`点击查看 ${row.employee.name} (${row.employee.role}) 的详细档案`}
                    >
                      <img
                        src={row.employee.avatar}
                        alt={row.employee.name}
                        className="w-9 h-9 rounded-full object-cover ring-2 ring-slate-100 group-hover/empCard:ring-blue-400 group-hover/empCard:scale-105 shrink-0 transition"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1">
                          <span className="text-xs font-extrabold text-slate-900 group-hover/empCard:text-blue-600 truncate transition">
                            {row.employee.name}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[10px] font-bold text-blue-600 bg-blue-50 px-1.5 py-0.2 rounded">
                            {row.employee.role}
                          </span>
                          {row.employee.preferredShift !== 'none' ? (
                            <span className="text-[9px] text-slate-400">
                              {row.employee.preferredShift === 'morning' ? '偏早' : '偏晚'}
                            </span>
                          ) : (
                            <span className="text-[9px] text-slate-300">无偏好</span>
                          )}
                          {isZeroShift && (
                            <span className="text-[9px] font-semibold text-slate-400 bg-slate-100 px-1 rounded">
                              本周未排
                            </span>
                          )}
                        </div>
                      </div>
                    </button>

                    {/* Shifts for 7 days */}
                    {row.shifts.map((shift) => (
                      <div key={shift.id} className="w-full">
                        <ShiftCard
                          shift={shift}
                          onClick={() => onShiftClick(row.employee.id, shift)}
                        />
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>

          </div>
        </div>
      )}
    </div>
  )
}
