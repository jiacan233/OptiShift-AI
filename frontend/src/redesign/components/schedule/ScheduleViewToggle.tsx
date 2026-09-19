import React from 'react'
import { User, CalendarDays, AlertTriangle } from 'lucide-react'
import { ViewMode } from '../../types/schedule'

interface ScheduleViewToggleProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  totalGaps?: number
  employeeCountText?: string
}

export const ScheduleViewToggle: React.FC<ScheduleViewToggleProps> = ({
  viewMode,
  onViewModeChange,
  totalGaps = 0,
  employeeCountText,
}) => {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-100">
      {/* Segmented Control Tabs */}
      <div className="inline-flex p-1 bg-slate-100/90 rounded-2xl border border-slate-200/70 select-none shadow-inner-xs">
        <button
          type="button"
          onClick={() => onViewModeChange('employee')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
            viewMode === 'employee'
              ? 'bg-white text-blue-700 shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/40'
          }`}
        >
          <User className="w-3.5 h-3.5" />
          <span>员工视图</span>
        </button>

        <button
          type="button"
          onClick={() => onViewModeChange('date')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
            viewMode === 'date'
              ? 'bg-white text-blue-700 shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/40'
          }`}
        >
          <CalendarDays className="w-3.5 h-3.5" />
          <span>日期视图</span>
          {totalGaps > 0 && (
            <span className="ml-1 inline-flex items-center gap-0.5 px-1.5 py-0.2 rounded-full bg-amber-100 text-amber-800 text-[10px] font-extrabold border border-amber-300 animate-pulse">
              <AlertTriangle className="w-2.5 h-2.5" />
              <span>{totalGaps} 缺口</span>
            </span>
          )}
        </button>
      </div>

      {/* Right description / context */}
      <div className="text-xs text-slate-500 font-medium flex items-center gap-2">
        {viewMode === 'employee' ? (
          <span>
            {employeeCountText || '员工全景排班'} · 回答“员工这一周怎么上班”
          </span>
        ) : (
          <span>
            7 日业务覆盖看板 · 回答“这一天谁上班、技能覆盖与人员缺口”
          </span>
        )}
      </div>
    </div>
  )
}
