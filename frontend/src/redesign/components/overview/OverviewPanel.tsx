import React from 'react'
import { ChevronRight } from 'lucide-react'
import { WeekMetrics } from '../../utils/scheduleSelectors'

interface OverviewPanelProps {
  weekMetrics?: WeekMetrics
  onSelectAlert?: (alert: WeekMetrics['alerts'][number]) => void
  onViewAllRules?: () => void
}

export const OverviewPanel: React.FC<OverviewPanelProps> = ({
  weekMetrics,
  onSelectAlert,
  onViewAllRules,
}) => {
  // Default values if weekMetrics is not yet passed
  const metrics: WeekMetrics = weekMetrics || {
    totalShifts: 0,
    compliantShifts: 0,
    coverageRate: 100,
    totalGaps: 0,
    totalHours: 0,
    totalLeaveEmployees: 0,
    activeEmployeesCount: 0,
    assignedEmployeesCount: 0,
    zeroShiftEmployeesCount: 0,
    alerts: [],
  }

  return (
    <div className="w-full xl:w-72 flex flex-col gap-4 shrink-0">
      {/* Overview Title with Live Status */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-900 tracking-tight">
          本周运营概览
        </h2>
        <span className="text-[11px] font-bold text-blue-600 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
          实时真实核算
        </span>
      </div>

      {/* Card 1: 人员与技能覆盖达标率 */}
      <div className="bg-white rounded-3xl p-4 border border-slate-150/70 shadow-sm flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold text-slate-400">人员与技能覆盖达标率</div>
          <div className="text-xl font-bold text-blue-600 mt-0.5">
            {metrics.coverageRate}%
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
            达标 {metrics.compliantShifts} / {metrics.totalShifts} 班次
          </div>
        </div>
      </div>

      {/* Card 2: 人员缺口 */}
      <div className="bg-white rounded-3xl p-4 border border-slate-150/70 shadow-sm flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold text-slate-400">在岗人员缺口</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span
              className={`text-xl font-extrabold ${
                metrics.totalGaps > 0 ? 'text-amber-600' : 'text-emerald-600'
              }`}
            >
              {metrics.totalGaps} 人
            </span>
            {metrics.totalGaps > 0 ? (
              <span className="inline-flex items-center text-[10px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-full">
                待补充
              </span>
            ) : (
              <span className="inline-flex items-center text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-full">
                满编
              </span>
            )}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
            {metrics.totalGaps > 0 ? '存在班次底线缺口' : '全周班次底线满足'}
          </div>
        </div>
      </div>

      {/* Card 3: 真实排班总工时 */}
      <div className="bg-white rounded-3xl p-4 border border-slate-150/70 shadow-sm flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold text-slate-400">排班总工时 (8h/班)</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-xl font-bold text-slate-900">
              {metrics.totalHours}h
            </span>
            <span className="inline-flex items-center text-[10px] font-bold text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full">
              {metrics.assignedEmployeesCount} / {metrics.activeEmployeesCount} 人已排班
            </span>
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
            {metrics.totalLeaveEmployees} 人在册请假
          </div>
        </div>
      </div>

      {/* Card 4: 规则与排班预警 (Shift Alerts) */}
      <div className="bg-white rounded-3xl p-4 border border-slate-150/70 shadow-sm flex flex-col justify-between flex-1">
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-slate-900">排班冲突与预警</h3>
            <span className="text-[10px] font-bold text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded-md">
              {metrics.alerts.length} 条
            </span>
          </div>

          <div className="space-y-2.5">
            {metrics.alerts.length === 0 ? (
              <div className="p-3 text-center text-xs text-slate-400 bg-slate-50 rounded-2xl border border-slate-100">
                当前周暂无覆盖缺口，完整校验见下方规则清单
              </div>
            ) : (
              metrics.alerts.map((alert) => (
                <div
                  key={alert.id}
                  onClick={() => alert.day ? onSelectAlert?.(alert) : onViewAllRules?.()}
                  className="flex items-start justify-between group cursor-pointer hover:bg-slate-50/80 p-2 -mx-1.5 rounded-xl transition border border-transparent hover:border-slate-150"
                >
                  <div className="flex items-start gap-2 min-w-0">
                    <span
                      className="w-2 h-2 rounded-full shrink-0 mt-1"
                      style={{ backgroundColor: alert.color }}
                    />
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-800 truncate">
                        {alert.title}
                      </div>
                      <div className="text-[10px] text-slate-400 leading-snug line-clamp-1">
                        {alert.subtitle}
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="w-3.5 h-3.5 text-slate-300 group-hover:text-slate-600 transition shrink-0 mt-0.5" />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="pt-3 mt-3 border-t border-slate-100">
          <button
            onClick={onViewAllRules}
            className="text-xs font-bold text-blue-600 hover:text-blue-700 flex items-center justify-between w-full transition"
          >
            <span>前往排班规则中心 (R-01~R-09)</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
