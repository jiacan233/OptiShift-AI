import React from 'react'
import { CheckCircle2, AlertTriangle, AlertCircle } from 'lucide-react'
import { DayCoverage, Employee } from '../../types/schedule'

interface DayCoverageCardProps {
  day: DayCoverage
  isSelected?: boolean
  onClick: (day: DayCoverage) => void
  onSelectEmployee?: (employee: Employee) => void
}

export const DayCoverageCard: React.FC<DayCoverageCardProps> = ({
  day,
  isSelected = false,
  onClick,
  onSelectEmployee,
}) => {
  const morningShift = day.shifts.find((s) => s.shiftType === 'morning')
  const eveningShift = day.shifts.find((s) => s.shiftType === 'evening')

  const morningAssigned = morningShift?.assignedCount ?? 0
  const morningRequired = morningShift?.requirementText ?? morningShift?.requiredCount ?? 4
  const morningGap = morningShift?.gapCount ?? 0
  const morningEmployees = morningShift?.employees ?? []

  const eveningAssigned = eveningShift?.assignedCount ?? 0
  const eveningRequired = eveningShift?.requirementText ?? eveningShift?.requiredCount ?? 4
  const eveningGap = eveningShift?.gapCount ?? 0
  const eveningEmployees = eveningShift?.employees ?? []

  const totalGaps = morningGap + eveningGap
  const isShortage = totalGaps > 0 || day.status === 'shortage'
  const isConflict = day.status === 'conflict' && totalGaps === 0

  // Max 3 avatars visible directly
  const morningVisible = morningEmployees.slice(0, 3)
  const morningRemaining = morningEmployees.length - 3

  const eveningVisible = eveningEmployees.slice(0, 3)
  const eveningRemaining = eveningEmployees.length - 3

  return (
    <div
      onClick={() => onClick(day)}
      className={`min-w-[115px] sm:min-w-[125px] flex-1 rounded-2xl p-2.5 sm:p-3 transition-all duration-150 cursor-pointer select-none border flex flex-col justify-between ${
        isSelected
          ? 'border-blue-500 ring-2 ring-blue-500/25 bg-blue-50/20 shadow-sm'
          : isConflict
          ? 'border-rose-200/90 hover:border-rose-300 bg-white hover:shadow-xs'
          : isShortage
          ? 'border-amber-200/90 hover:border-amber-300 bg-white hover:shadow-xs'
          : 'border-slate-200/80 hover:border-slate-300 bg-white hover:shadow-xs'
      }`}
    >
      <div className="space-y-2">
        {/* Row 1: Header (2-line layout: Line 1 Date, Line 2 Status Badge) */}
        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-1">
            <div className="flex items-baseline gap-1 min-w-0">
              <span className="text-xs sm:text-[13px] font-black text-slate-900 tracking-tight">
                {day.day}
              </span>
              <span className="text-[11px] font-semibold text-slate-400">
                {day.fullDate ? day.fullDate.slice(5).replace('-', '/') : `${String(day.date).padStart(2, '0')}日`}
              </span>
            </div>
            <span className="text-[10px] font-semibold text-slate-400 shrink-0">
              {day.dayCn}
            </span>
          </div>

          {/* Status Badge on its own line: never crowded or squeezed */}
          <div>
            {!isShortage && !isConflict && (
              <span className="inline-flex items-center gap-1 text-[9px] sm:text-[10px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-md border border-emerald-200/70">
                <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500 shrink-0" />
                <span>正常</span>
              </span>
            )}

            {isShortage && (
              <span className="inline-flex items-center gap-1 text-[9px] sm:text-[10px] font-bold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded-md border border-amber-300/80">
                <AlertTriangle className="w-2.5 h-2.5 text-amber-500 shrink-0" />
                <span>{totalGaps > 0 ? `${totalGaps}个缺口` : '缺口'}</span>
              </span>
            )}

            {isConflict && (
              <span className="inline-flex items-center gap-1 text-[9px] sm:text-[10px] font-bold text-rose-700 bg-rose-50 px-1.5 py-0.5 rounded-md border border-rose-200">
                <AlertCircle className="w-2.5 h-2.5 text-rose-500 shrink-0" />
                <span>规则冲突</span>
              </span>
            )}
          </div>
        </div>

        {/* Row 2: Metrics (已排人数 & 排班时长) */}
        <div className="grid grid-cols-2 gap-1 py-1.5 border-b border-slate-100/90">
          <div>
            <div className="text-sm sm:text-base font-extrabold text-slate-900 leading-tight">
              {day.totalEmployees}
            </div>
            <div className="text-[10px] font-medium text-slate-400 leading-tight mt-0.5">
              已排人数
            </div>
          </div>
          <div>
            <div className="text-sm sm:text-base font-extrabold text-slate-900 leading-tight">
              {day.totalHours}h
            </div>
            <div className="text-[10px] font-medium text-slate-400 leading-tight mt-0.5">
              排班时长
            </div>
          </div>
        </div>

        {/* Row 3: 早班 (Morning Shift) */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
              <span className="text-[11px] font-bold text-slate-700">早班</span>
            </div>
            <span
              className={`text-[11px] font-extrabold ${
                morningGap > 0 ? 'text-amber-600' : 'text-slate-700'
              }`}
            >
              {morningAssigned} / {morningRequired}
            </span>
          </div>

          {/* Morning Avatar Group */}
          <div className="flex items-center -space-x-1.5 pt-0.5 pl-0.5 min-h-[24px]">
            {morningVisible.map((emp) => (
              <img
                key={emp.id}
                src={emp.avatar}
                alt={emp.name}
                title={`点击查看 ${emp.name} (${emp.role}) 的档案详情`}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelectEmployee?.(emp)
                }}
                className="w-[22px] h-[22px] rounded-full object-cover ring-2 ring-white shadow-xs shrink-0 bg-slate-100 hover:scale-125 hover:ring-blue-400 hover:z-20 transition-all cursor-pointer"
              />
            ))}
            {morningRemaining > 0 && (
              <span
                title={morningEmployees
                  .slice(3)
                  .map((e) => `${e.name} (${e.role})`)
                  .join('、')}
                className="inline-flex items-center justify-center w-[22px] h-[22px] rounded-full bg-blue-50 border border-blue-200/80 text-blue-600 text-[9px] font-extrabold ring-2 ring-white shrink-0"
              >
                +{morningRemaining}
              </span>
            )}
            {morningEmployees.length === 0 && (
              <span className="text-[10px] text-slate-300 font-normal">暂无排班</span>
            )}
          </div>
        </div>

        {/* Row 4: 晚班 (Evening Shift) */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-500 shrink-0" />
              <span className="text-[11px] font-bold text-slate-700">晚班</span>
            </div>
            <span
              className={`text-[11px] font-extrabold ${
                eveningGap > 0 ? 'text-amber-600' : 'text-slate-700'
              }`}
            >
              {eveningAssigned} / {eveningRequired}
            </span>
          </div>

          {/* Evening Avatar Group */}
          <div className="flex items-center -space-x-1.5 pt-0.5 pl-0.5 min-h-[24px]">
            {eveningVisible.map((emp) => (
              <img
                key={emp.id}
                src={emp.avatar}
                alt={emp.name}
                title={`点击查看 ${emp.name} (${emp.role}) 的档案详情`}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelectEmployee?.(emp)
                }}
                className="w-[22px] h-[22px] rounded-full object-cover ring-2 ring-white shadow-xs shrink-0 bg-slate-100 hover:scale-125 hover:ring-blue-400 hover:z-20 transition-all cursor-pointer"
              />
            ))}
            {eveningRemaining > 0 && (
              <span
                title={eveningEmployees
                  .slice(3)
                  .map((e) => `${e.name} (${e.role})`)
                  .join('、')}
                className="inline-flex items-center justify-center w-[22px] h-[22px] rounded-full bg-purple-50 border border-purple-200/80 text-purple-600 text-[9px] font-extrabold ring-2 ring-white shrink-0"
              >
                +{eveningRemaining}
              </span>
            )}
            {eveningEmployees.length === 0 && (
              <span className="text-[10px] text-slate-300 font-normal">暂无排班</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
