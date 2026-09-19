import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  X,
  Check,
  Minus,
  Sun,
  Moon,
  Clock,
  CalendarOff,
  ShieldCheck,
  Calendar,
} from 'lucide-react'
import { Employee, SkillType } from '../../types/schedule'
import {
  getCleanName,
  ROLE_BADGE_STYLES,
  DAYS_CN_MAP,
} from './employeeUtils'
import { getSkillMeta } from './skillConfig'

const ALL_SKILLS: SkillType[] = ['店长值守', '饮品制作', '收银', '库存管理']

const DEFAULT_DAYS_HEADER = [
  { day: 'Mon', dayCn: '周一', date: 5 },
  { day: 'Tue', dayCn: '周二', date: 6 },
  { day: 'Wed', dayCn: '周三', date: 7 },
  { day: 'Thu', dayCn: '周四', date: 8 },
  { day: 'Fri', dayCn: '周五', date: 9 },
  { day: 'Sat', dayCn: '周六', date: 10 },
  { day: 'Sun', dayCn: '周日', date: 11 },
]

interface EmployeeDetailDrawerProps {
  employee: Employee | null
  isOpen: boolean
  onClose: () => void
  availableSkills?: SkillType[]
  daysHeader?: { day: string; dayCn: string; date: number }[]
}

export const EmployeeDetailDrawer: React.FC<EmployeeDetailDrawerProps> = ({
  employee,
  isOpen,
  onClose,
  availableSkills = ALL_SKILLS,
  daysHeader = DEFAULT_DAYS_HEADER,
}) => {
  // Handle ESC key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown)
    }
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen || !employee) return null

  const cleanName = getCleanName(employee.name)
  const roleBadgeStyle =
    ROLE_BADGE_STYLES[employee.role] || 'bg-slate-100 text-slate-600 border-slate-200'
  const hoursRatio = employee.currentHours / (employee.maxHoursPerWeek || 40)
  const isHoursFull = employee.currentHours >= employee.maxHoursPerWeek
  const isHoursNear = !isHoursFull && employee.currentHours >= employee.maxHoursPerWeek - 8

  const drawerContent = (
    <div className="fixed inset-0 z-50 pointer-events-none">
      {/* Dim Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-slate-900/35 backdrop-blur-xs transition-opacity animate-fade-in pointer-events-auto"
      />

      {/* Slide-in Drawer Container: Top baseline perfectly aligned with Dashboard Shell Card */}
      <div className="fixed top-3 md:top-6 lg:top-7 bottom-3 md:bottom-6 lg:bottom-7 right-3 md:right-6 lg:right-7 w-[calc(100%-24px)] sm:w-[480px] max-w-[480px] bg-white shadow-2xl rounded-3xl border border-slate-200/80 flex flex-col z-10 animate-slide-in-right overflow-hidden pointer-events-auto">
        {/* Drawer Header: 3-column grid with unified top alignment */}
        <div className="p-5 border-b border-slate-150 bg-slate-50/60 grid grid-cols-[auto_1fr_auto] gap-4 items-start">
          {/* Col 1: Employee Image */}
          <img
            src={employee.avatar}
            alt={cleanName}
            className="w-[135px] sm:w-[145px] h-[92px] sm:h-[98px] rounded-2xl object-cover ring-1 ring-slate-200/90 shadow-2xs shrink-0 self-start"
          />

          {/* Col 2: Employee Meta (aligned with top of image) */}
          <div className="min-w-0 self-start">
            {/* Row 1: Name + Role Badge (aligned vertically with each other) */}
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base sm:text-lg font-bold text-slate-900 leading-tight truncate">
                {cleanName}
              </h3>
              <span
                className={`text-[11px] font-bold px-2 py-0.5 rounded-lg border shrink-0 leading-tight ${roleBadgeStyle}`}
              >
                {employee.role}
              </span>
            </div>

            {/* Row 2: Employee ID & Weekly Max Hours */}
            <div className="text-xs text-slate-500 font-medium space-y-1 pt-1.5">
              <div className="flex items-center gap-1 font-mono">
                <span className="text-slate-400">工号：</span>
                <span className="text-slate-700 font-semibold">{employee.id}</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-slate-400">周工时上限：</span>
                <span className="text-slate-700 font-semibold font-mono">
                  {employee.maxHoursPerWeek}h
                </span>
              </div>
            </div>
          </div>

          {/* Col 3: Close Button (aligned to Header top) */}
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 flex items-center justify-center transition shrink-0 self-start -mr-1"
            aria-label="关闭抽屉"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-5 text-xs">
          {/* Section 1: 本周工时与负荷 */}
          <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200/70">
            <div className="flex items-center justify-between mb-2">
              <span className="font-bold text-slate-700 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-blue-600" />
                本周排班工时负荷
              </span>
              <span className="font-extrabold text-slate-900 text-sm">
                {employee.currentHours}{' '}
                <span className="text-slate-400 text-xs font-normal">
                  / {employee.maxHoursPerWeek}h
                </span>
              </span>
            </div>

            <div className="w-full bg-slate-200/80 h-2.5 rounded-full overflow-hidden">
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

            <div className="flex items-center justify-between text-[11px] text-slate-500 mt-2 font-medium">
              <span>负荷率: {Math.round(hoursRatio * 100)}%</span>
              <span>
                {isHoursFull ? (
                  <span className="text-amber-700 font-bold bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                    工时已满
                  </span>
                ) : isHoursNear ? (
                  <span className="text-slate-700 font-semibold bg-slate-100 px-2 py-0.5 rounded">
                    接近工时上限
                  </span>
                ) : (
                  <span className="text-slate-600 font-semibold">可继续排班</span>
                )}
              </span>
            </div>
          </div>

          {/* Section 2: 班次偏好 */}
          <div className="bg-white rounded-2xl p-4 border border-slate-200/70">
            <div className="font-bold text-slate-700 text-xs mb-2 flex items-center gap-1.5">
              <span>班次偏好</span>
            </div>

            {employee.preferredShift === 'morning' ? (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-sky-50 border border-sky-200/80 text-sky-800">
                <Sun className="w-4 h-4 text-sky-600 shrink-0" />
                <div>
                  <div className="font-bold">偏好早班 (09:00 - 17:00)</div>
                  <div className="text-[11px] text-sky-600/80 mt-0.5">
                    求解器软约束 (R-07) 将优先为其匹配早班时段
                  </div>
                </div>
              </div>
            ) : employee.preferredShift === 'evening' ? (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-indigo-50 border border-indigo-200/80 text-indigo-800">
                <Moon className="w-4 h-4 text-indigo-600 shrink-0" />
                <div>
                  <div className="font-bold">偏好晚班 (13:00 - 21:00)</div>
                  <div className="text-[11px] text-indigo-600/80 mt-0.5">
                    求解器软约束 (R-07) 将优先为其匹配晚班时段
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-600">
                <div className="font-semibold">班次不限</div>
                <div className="text-[11px] text-slate-400 mt-0.5">
                  早班、晚班均可正常承接，无特殊时间倾向
                </div>
              </div>
            )}
          </div>

          {/* Section 3: 认证技能矩阵 */}
          <div className="bg-white rounded-2xl p-4 border border-slate-200/70">
            <div className="font-bold text-slate-700 text-xs mb-2.5 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-blue-600" />
                技能认证资格 (R-09 技能保真)
              </span>
              <span className="text-[11px] text-slate-400 font-normal">
                已具备 {employee.skills.length} / {availableSkills.length}
              </span>
            </div>

            <div className="space-y-1.5">
              {availableSkills.map((skill) => {
                const hasSkill = employee.skills.includes(skill)
                const meta = getSkillMeta(skill)
                const SkillIcon = meta.icon

                return (
                  <div
                    key={skill}
                    className={`flex items-center justify-between p-2.5 rounded-xl border transition ${
                      hasSkill
                        ? 'bg-slate-50/70 border-slate-200'
                        : 'bg-white border-slate-100 opacity-60'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-5 h-5 rounded-md flex items-center justify-center text-xs font-bold ${
                          hasSkill
                            ? 'bg-emerald-500 text-white'
                            : 'bg-slate-200 text-slate-400'
                        }`}
                      >
                        {hasSkill ? <Check className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                      </span>
                      <SkillIcon
                        className={`w-3.5 h-3.5 ${hasSkill ? meta.iconColor : 'text-slate-400'}`}
                      />
                      <span className="font-bold text-slate-800">{skill}</span>
                    </div>

                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-md border ${
                        hasSkill ? meta.badgeStyle : 'bg-slate-50 text-slate-400 border-slate-200'
                      }`}
                    >
                      {hasSkill ? '已认证合格' : '未具备'}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Section 4: 本周请假与不可用记录 (R-08 绝对禁排) */}
          <div className="bg-white rounded-2xl p-4 border border-slate-200/70">
            <div className="font-bold text-slate-700 text-xs mb-2 flex items-center gap-1.5">
              <CalendarOff className="w-3.5 h-3.5 text-rose-500" />
              <span>本周请假锁定 (R-08 绝对禁排)</span>
            </div>

            {employee.leaveDays.length > 0 ? (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800">
                <div className="font-bold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-rose-500" />
                  已批准休假：周
                  {employee.leaveDays.map((d) => DAYS_CN_MAP[d] || d).join('、')}
                </div>
                <p className="text-[11px] text-rose-600/90 mt-1">
                  该员工已完成休假审批，求解器已硬性锁定该日期，禁止分配任何排班与值守任务。
                </p>
              </div>
            ) : (
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-500 text-center font-medium">
                本周无审批休假记录
              </div>
            )}
          </div>

          {/* Section 5: 本周 7 天可用性 */}
          <div className="bg-white rounded-2xl p-4 border border-slate-200/70">
            <div className="font-bold text-slate-700 text-xs mb-2.5 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-slate-600" />
                全周可用性日程
              </span>
            </div>

            <div className="divide-y divide-slate-100 border border-slate-100 rounded-xl overflow-hidden">
              {daysHeader.map((dayItem) => {
                const isLeave = employee.leaveDays.includes(dayItem.day)
                const isAvailable = employee.availableDays.includes(dayItem.day)

                return (
                  <div
                    key={dayItem.day}
                    className="flex items-center justify-between p-2.5 bg-slate-50/40 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-800">{dayItem.dayCn}</span>
                      <span className="text-[11px] text-slate-400">
                        {String(dayItem.date).padStart(2, '0')}日
                      </span>
                    </div>

                    <div>
                      {isLeave ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-md">
                          已批准请假 (禁排)
                        </span>
                      ) : isAvailable ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md">
                          <Check className="w-3 h-3" /> 可排班
                        </span>
                      ) : (
                        <span className="text-[10px] font-medium text-slate-400 bg-slate-100 px-2 py-0.5 rounded-md">
                          受限不可用
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Drawer Footer */}
        <div className="p-4 border-t border-slate-150 bg-slate-50/80 flex items-center justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 font-bold rounded-xl text-xs transition"
          >
            关闭详情
          </button>
        </div>
      </div>
    </div>
  )

  if (typeof document !== 'undefined') {
    return createPortal(drawerContent, document.body)
  }
  return drawerContent
}
