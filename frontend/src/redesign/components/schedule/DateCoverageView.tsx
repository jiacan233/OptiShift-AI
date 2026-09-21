import React, { useState } from 'react'
import { staffingRequirementText } from '@/lib/presentation'
import {
  CalendarX,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  Sun,
  Moon,
  Plus,
  UserPlus,
  Bot,
  ChevronLeft,
  ChevronRight,
  FileText,
} from 'lucide-react'
import { DayCoverage, ShiftCoverage, Employee } from '../../types/schedule'
import { DayCoverageCard } from './DayCoverageCard'
import { AssignedEmployeeChip } from './AssignedEmployeeChip'
import { EmployeeDetailDrawer } from '../employees/EmployeeDetailDrawer'
import { useAppStore } from '@/store/AppStore'

interface DateCoverageViewProps {
  dayCoverages: DayCoverage[]
  selectedDate: DayCoverage | null
  onSelectDay: (day: DayCoverage) => void
  onAddShiftForSlot?: (date: string, shiftType: 'morning' | 'evening') => void
  onAskAiForDay?: (day: DayCoverage, shift?: ShiftCoverage) => void
  addShiftDisabled: boolean
  aiDisabled: boolean
  onGenerateSchedule?: () => void
  onSelectEmployee?: (employee: Employee) => void
}

export const DateCoverageView: React.FC<DateCoverageViewProps> = ({
  dayCoverages,
  selectedDate,
  onSelectDay,
  onAddShiftForSlot,
  onAskAiForDay,
  addShiftDisabled,
  aiDisabled,
  onGenerateSchedule,
  onSelectEmployee,
}) => {
  // Selected employee for detail drawer
  const [selectedEmployeeForDrawer, setSelectedEmployeeForDrawer] = useState<Employee | null>(null)
  const store = useAppStore()
  const authViolations = store.result?.validation?.authorized_violations ?? []

  if (!dayCoverages || dayCoverages.length === 0) {
    return (
      <div className="bg-white rounded-3xl p-12 border border-slate-200/80 text-center space-y-4 shadow-xs">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
          <CalendarX className="w-6 h-6" />
        </div>
        <div>
          <h3 className="text-base font-bold text-slate-800">暂无日期覆盖数据</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            当前周次未检测到日期覆盖结果，请先生成排班或切换周次。
          </p>
        </div>
        {onGenerateSchedule && (
          <button
            type="button"
            onClick={onGenerateSchedule}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold shadow-sm transition"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>立即生成排班</span>
          </button>
        )}
      </div>
    )
  }

  // Determine active day (default to selectedDate, or Wednesday, or first day)
  const activeDay =
    selectedDate ||
    dayCoverages.find((d) => d.day === 'Wed') ||
    dayCoverages[0]

  const currentIndex = dayCoverages.findIndex((d) => d.day === activeDay.day)

  const handlePrevDay = () => {
    if (currentIndex > 0) {
      onSelectDay(dayCoverages[currentIndex - 1])
    } else {
      onSelectDay(dayCoverages[dayCoverages.length - 1])
    }
  }

  const handleNextDay = () => {
    if (currentIndex < dayCoverages.length - 1) {
      onSelectDay(dayCoverages[currentIndex + 1])
    } else {
      onSelectDay(dayCoverages[0])
    }
  }

  const handleEmployeeClick = (emp: Employee) => {
    if (onSelectEmployee) {
      onSelectEmployee(emp)
    } else {
      setSelectedEmployeeForDrawer(emp)
    }
  }

  // Active day shifts
  const morningShift = activeDay.shifts.find((s) => s.shiftType === 'morning')
  const eveningShift = activeDay.shifts.find((s) => s.shiftType === 'evening')

  const morningAssigned = morningShift?.assignedCount ?? 0
  const morningRequired = morningShift?.requirementText ?? morningShift?.requiredCount ?? 4
  const morningGap = morningShift?.gapCount ?? 0
  const morningEmployees = morningShift?.employees ?? []

  const eveningAssigned = eveningShift?.assignedCount ?? 0
  const eveningRequired = eveningShift?.requirementText ?? eveningShift?.requiredCount ?? 4
  const eveningGap = eveningShift?.gapCount ?? 0
  const eveningEmployees = eveningShift?.employees ?? []

  const totalDayGaps = morningGap + eveningGap
  const isDayShortage = totalDayGaps > 0 || activeDay.status === 'shortage'
  const isDayConflict = activeDay.status === 'conflict' && totalDayGaps === 0

  const formattedDate = activeDay.fullDate
    ? `${activeDay.fullDate.slice(5, 7)}月${activeDay.fullDate.slice(8, 10)}日`
    : `${activeDay.date < 10 ? `0${activeDay.date}` : activeDay.date}日`

  return (
    <div className="space-y-4 animate-fade-in">
      {/* 1. Top 7-Day Coverage Board Grid: Strictly in 1 row, horizontally scrollable on mobile */}
      <div className="overflow-x-auto pb-1 -mx-0.5 px-0.5 custom-scrollbar">
        <div className="flex gap-2 sm:gap-2.5 min-w-[830px] xl:min-w-0">
          {dayCoverages.map((day) => (
            <DayCoverageCard
              key={day.day}
              day={day}
              isSelected={activeDay.day === day.day}
              onClick={onSelectDay}
              onSelectEmployee={handleEmployeeClick}
            />
          ))}
        </div>
      </div>

      {/* 2. Selected Day Detail Area (Directly below the 7 Day Cards) */}
      <div className="bg-white rounded-3xl p-5 sm:p-6 border border-slate-200/80 shadow-xs space-y-4">
        {/* Day Detail Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h3 className="text-base sm:text-lg font-black text-slate-900 tracking-tight">
                {formattedDate} ({activeDay.dayCn})
              </h3>

              {isDayShortage && (
                <span className="inline-flex items-center gap-1 text-xs font-extrabold text-amber-700 bg-amber-50 px-2.5 py-0.5 rounded-full border border-amber-300/80">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                  <span>当天共有 {totalDayGaps > 0 ? totalDayGaps : activeDay.conflictCount} 个岗位缺口，建议尽快补充</span>
                </span>
              )}

              {isDayConflict && (
                <span className="inline-flex items-center gap-1 text-xs font-extrabold text-rose-700 bg-rose-50 px-2.5 py-0.5 rounded-full border border-rose-200">
                  <AlertCircle className="w-3.5 h-3.5 text-rose-500" />
                  <span>存在规则冲突，请优先排查</span>
                </span>
              )}

              {!isDayShortage && !isDayConflict && (
                <span className="inline-flex items-center gap-1 text-xs font-extrabold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200/80">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                  <span>人员与技能覆盖正常</span>
                </span>
              )}
            </div>

            {activeDay.staffingCheck && <p className={`text-xs mt-1 font-semibold ${activeDay.staffingCheck.passed ? 'text-emerald-600' : 'text-rose-600'}`}>
              全天人数：{activeDay.staffingCheck.actual} / {staffingRequirementText(activeDay.staffingCheck)} 人
            </p>}
            <p className="text-xs text-slate-400 mt-1 font-medium">
              {activeDay.dayCn === '周六' || activeDay.dayCn === '周日'
                ? `${activeDay.dayCn} · 周末大客流高峰期，请确保收银与吧台制作人员满编`

                : `${activeDay.dayCn} · 门店日常运营时段，保障关键岗位人员基线与技能值守`}
            </p>
          </div>

          {/* Prev / Next day switcher */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handlePrevDay}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-slate-200 bg-white hover:bg-slate-50 text-xs font-bold text-slate-700 shadow-2xs active:scale-95 transition"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>上一天</span>
            </button>
            <button
              type="button"
              onClick={handleNextDay}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-slate-200 bg-white hover:bg-slate-50 text-xs font-bold text-slate-700 shadow-2xs active:scale-95 transition"
            >
              <span>下一天</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Early Shift (早班) Card */}
        <div className="rounded-2xl p-4 sm:p-5 border border-slate-200/90 bg-[#FAFAFA] space-y-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-xl bg-blue-100/70 text-blue-600 flex items-center justify-center shrink-0">
                <Sun className="w-4 h-4 text-blue-600" />
              </div>
              <span className="text-sm font-black text-blue-600">早班</span>
              <span className="text-xs text-slate-500 font-medium">
                {morningShift?.timeRange || '09:00 - 17:00'}
              </span>

              {morningShift?.isCompliant ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200/80">
                  <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                  <span>排班正常</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-300/80">
                  <AlertTriangle className="w-3 h-3 text-amber-500" />
                  <span>{morningGap > 0 ? `${morningGap} 个缺口` : '规则告警'}</span>
                </span>
              )}
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-black text-slate-800">
                  {morningAssigned} / {morningRequired} 人
                </span>
                <div className="w-20 sm:w-28 h-2 rounded-full bg-slate-200/80 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      morningGap > 0 ? 'bg-amber-500' : 'bg-blue-500'
                    }`}
                    style={{
                      width: `${Math.min(100, Math.round((morningAssigned / Math.max(1, morningShift?.requiredCount ?? 4)) * 100))}%`,
                    }}
                  />
                </div>
                <span className="text-[11px] font-extrabold text-slate-500">
                  {Math.round((morningAssigned / Math.max(1, morningShift?.requiredCount ?? 4)) * 100)}%
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={addShiftDisabled || !onAddShiftForSlot}
                  onClick={() => onAddShiftForSlot?.(activeDay.fullDate, 'morning')}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl border border-blue-200 bg-white text-blue-600 hover:bg-blue-50 text-xs font-bold transition shadow-2xs"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>补充员工</span>
                </button>
                <button
                  type="button"
                  disabled={aiDisabled || !onAskAiForDay}
                  onClick={() => onAskAiForDay?.(activeDay, morningShift)}
                  className="inline-flex items-center gap-1 px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition shadow-xs"
                >
                  <Bot className="w-3.5 h-3.5" />
                  <span>AI 调配建议</span>
                </button>
              </div>
            </div>
          </div>

          {/* Morning 3-Column Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 pt-3.5 border-t border-slate-200/70 items-start">
            {/* Col 1: 排班员工 (Avatar + Name + Role Chip) */}
            <div className="lg:col-span-4 space-y-2">
              <div className="text-[11px] font-bold text-slate-400">
                排班员工 ({morningEmployees.length})
              </div>
              <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                {morningEmployees.map((emp) => {
                  const match = authViolations.find(
                    (v) => v.employee_id === emp.id && v.day === activeDay.day && (!v.shift || v.shift === 'morning')
                  )
                  return (
                    <AssignedEmployeeChip
                      key={emp.id}
                      employee={emp}
                      warning={match ? `⚠ ${match.rule_id} 强制安排` : undefined}
                      onClick={handleEmployeeClick}
                    />
                  )
                })}
                {morningEmployees.length === 0 && (
                  <span className="text-xs text-slate-400 font-medium py-1">
                    暂无排班员工
                  </span>
                )}
                <button
                  type="button"
                  disabled={addShiftDisabled || !onAddShiftForSlot}
                  onClick={() => onAddShiftForSlot?.(activeDay.fullDate, 'morning')}
                  className="w-7 h-7 rounded-full border border-dashed border-blue-300 text-blue-500 hover:text-blue-700 hover:bg-blue-50 hover:border-blue-400 flex items-center justify-center transition shadow-2xs cursor-pointer shrink-0"
                  title="为早班补充员工"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Col 2: 技能与成员覆盖 */}
            <div className="lg:col-span-5 space-y-2">
              <div className="text-[11px] font-bold text-slate-400">
                技能与成员覆盖
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {morningShift && morningShift.managerCount >= morningShift.managerRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>店长值守 {morningShift.managerCount}/{morningShift.managerRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-50 px-2.5 py-1 rounded-full border border-rose-200">
                    <AlertTriangle className="w-3 h-3 text-rose-500" />
                    <span>店长值守 {morningShift?.managerCount || 0}/{morningShift?.managerRequired ?? 1}</span>
                  </span>
                )}

                {morningShift && morningShift.cashierCount >= morningShift.cashierRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>收银操作 {morningShift.cashierCount}/{morningShift.cashierRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full border border-amber-300">
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                    <span>收银操作 {morningShift?.cashierCount || 0}/{morningShift?.cashierRequired ?? 1}</span>
                  </span>
                )}

                {morningShift && morningShift.baristaCount >= morningShift.beverageRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>饮品制作 {morningShift.baristaCount}/{morningShift.beverageRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full border border-amber-300">
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                    <span>饮品制作 {morningShift?.baristaCount || 0}/{morningShift?.beverageRequired ?? 2}</span>
                  </span>
                )}
              </div>
            </div>

            {/* Col 3: 班次说明 */}
            <div className="lg:col-span-3 space-y-1 text-xs">
              <div className="text-[11px] font-bold text-slate-400">
                班次说明
              </div>
              <div className="flex items-start gap-2 text-slate-600">
                <FileText className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-0.5" />
                <div className="text-[11px] leading-relaxed">
                  <div className="font-semibold text-slate-700">
                    班次: {morningShift?.timeRange || '09:00 - 17:00'}
                  </div>
                  <div className="text-slate-400 mt-0.5">
                    需重点关注高峰客流量，确保前场服务质量。
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Evening Shift (晚班) Card */}
        <div className="rounded-2xl p-4 sm:p-5 border border-slate-200/90 bg-[#FAFAFA] space-y-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-xl bg-purple-100/70 text-purple-600 flex items-center justify-center shrink-0">
                <Moon className="w-4 h-4 text-purple-600" />
              </div>
              <span className="text-sm font-black text-purple-600">晚班</span>
              <span className="text-xs text-slate-500 font-medium">
                {eveningShift?.timeRange || '13:00 - 21:00'}
              </span>

              {eveningShift?.isCompliant ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200/80">
                  <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                  <span>排班正常</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-300/80">
                  <AlertTriangle className="w-3 h-3 text-amber-500" />
                  <span>{eveningGap > 0 ? `${eveningGap} 个缺口` : '规则告警'}</span>
                </span>
              )}
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-black text-slate-800">
                  {eveningAssigned} / {eveningRequired} 人
                </span>
                <div className="w-20 sm:w-28 h-2 rounded-full bg-slate-200/80 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      eveningGap > 0 ? 'bg-amber-500' : 'bg-purple-500'
                    }`}
                    style={{
                      width: `${Math.min(100, Math.round((eveningAssigned / Math.max(1, eveningShift?.requiredCount ?? 4)) * 100))}%`,
                    }}
                  />
                </div>
                <span className="text-[11px] font-extrabold text-slate-500">
                  {Math.round((eveningAssigned / Math.max(1, eveningShift?.requiredCount ?? 4)) * 100)}%
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={addShiftDisabled || !onAddShiftForSlot}
                  onClick={() => onAddShiftForSlot?.(activeDay.fullDate, 'evening')}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl border border-blue-200 bg-white text-blue-600 hover:bg-blue-50 text-xs font-bold transition shadow-2xs"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>补充员工</span>
                </button>
                <button
                  type="button"
                  disabled={aiDisabled || !onAskAiForDay}
                  onClick={() => onAskAiForDay?.(activeDay, eveningShift)}
                  className="inline-flex items-center gap-1 px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition shadow-xs"
                >
                  <Bot className="w-3.5 h-3.5" />
                  <span>AI 调配建议</span>
                </button>
              </div>
            </div>
          </div>

          {/* Evening 3-Column Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 pt-3.5 border-t border-slate-200/70 items-start">
            {/* Col 1: 排班员工 (Avatar + Name + Role Chip) */}
            <div className="lg:col-span-4 space-y-2">
              <div className="text-[11px] font-bold text-slate-400">
                排班员工 ({eveningEmployees.length})
              </div>
              <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                {eveningEmployees.map((emp) => {
                  const match = authViolations.find(
                    (v) => v.employee_id === emp.id && v.day === activeDay.day && (!v.shift || v.shift === 'evening')
                  )
                  return (
                    <AssignedEmployeeChip
                      key={emp.id}
                      employee={emp}
                      warning={match ? `⚠ ${match.rule_id} 强制安排` : undefined}
                      onClick={handleEmployeeClick}
                    />
                  )
                })}
                {eveningEmployees.length === 0 && (
                  <span className="text-xs text-slate-400 font-medium py-1">
                    暂无排班员工
                  </span>
                )}
                <button
                  type="button"
                  disabled={addShiftDisabled || !onAddShiftForSlot}
                  onClick={() => onAddShiftForSlot?.(activeDay.fullDate, 'evening')}
                  className="w-7 h-7 rounded-full border border-dashed border-blue-300 text-blue-500 hover:text-blue-700 hover:bg-blue-50 hover:border-blue-400 flex items-center justify-center transition shadow-2xs cursor-pointer shrink-0"
                  title="为晚班补充员工"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Col 2: 技能与成员覆盖 */}
            <div className="lg:col-span-5 space-y-2">
              <div className="text-[11px] font-bold text-slate-400">
                技能与成员覆盖
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {eveningShift && eveningShift.baristaCount >= eveningShift.beverageRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>饮品制作 {eveningShift.baristaCount}/{eveningShift.beverageRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full border border-amber-300">
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                    <span>饮品制作 {eveningShift?.baristaCount || 0}/{eveningShift?.beverageRequired ?? 2}</span>
                  </span>
                )}

                {eveningShift && eveningShift.cashierCount >= eveningShift.cashierRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>收银 {eveningShift.cashierCount}/{eveningShift.cashierRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full border border-amber-300">
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                    <span>收银 {eveningShift?.cashierCount || 0}/{eveningShift?.cashierRequired ?? 1}</span>
                  </span>
                )}

                {eveningShift && eveningShift.managerCount >= eveningShift.managerRequired ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/70">
                    <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    <span>店长值守 {eveningShift.managerCount}/{eveningShift.managerRequired}</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-50 px-2.5 py-1 rounded-full border border-rose-200">
                    <AlertTriangle className="w-3 h-3 text-rose-500" />
                    <span>店长值守 {eveningShift?.managerCount || 0}/{eveningShift?.managerRequired ?? 1}</span>
                  </span>
                )}
              </div>
            </div>

            {/* Col 3: 班次说明 */}
            <div className="lg:col-span-3 space-y-1 text-xs">
              <div className="text-[11px] font-bold text-slate-400">
                班次说明
              </div>
              <div className="flex items-start gap-2 text-slate-600">
                <FileText className="w-3.5 h-3.5 text-purple-500 shrink-0 mt-0.5" />
                <div className="text-[11px] leading-relaxed">
                  <div className="font-semibold text-slate-700">
                    班次: {eveningShift?.timeRange || '13:00 - 21:00'}
                  </div>
                  <div className="text-slate-400 mt-0.5">
                    值守人员与技能要求以当前排班规则为准。
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 3. AI 排班建议 (AI Recommendation Box) */}
        <div className="bg-[#f0f6ff] border border-blue-200/80 rounded-2xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-600 text-white font-black text-sm flex items-center justify-center shrink-0 shadow-xs">
              Hi
            </div>
            <div className="space-y-1">
              <div className="text-xs font-black text-slate-800">覆盖检查与调配建议</div>
              <ul className="text-xs text-slate-600 space-y-1">
                {activeDay.shifts.flatMap(shift => shift.ruleIssues.map((issue, index) => <li key={`${shift.shiftType}-${issue.ruleId}-${index}`}>
                  {shift.shiftName} · {issue.ruleId}：{issue.message}
                </li>))}
                <li>人员与技能覆盖不代表全部规则通过，确认排班前请查看完整规则校验。</li>
              </ul>
            </div>
          </div>

          <button
            type="button"
            disabled={aiDisabled || !onAskAiForDay}
            onClick={() => onAskAiForDay?.(activeDay)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white border border-blue-300 text-blue-600 hover:bg-blue-50/80 text-xs font-extrabold shadow-2xs shrink-0 transition"
          >
            <Sparkles className="w-3.5 h-3.5 text-blue-600" />
            <span>分析调配建议</span>
          </button>
        </div>
      </div>

      {/* Reusable Employee Profile Detail Drawer */}
      <EmployeeDetailDrawer
        daysHeader={dayCoverages}
        employee={selectedEmployeeForDrawer}
        isOpen={!!selectedEmployeeForDrawer}
        onClose={() => setSelectedEmployeeForDrawer(null)}
      />
    </div>
  )
}
