import { useState, useMemo } from 'react'
import {
  BarChart3,
  CalendarDays,
  CalendarPlus,
  Check,
  ChevronDown,
  ChevronUp,
  GitCompareArrows,
  ListChecks,
  LoaderCircle,
  MessageCircleMore,
  ShieldCheck,
  Umbrella,
  X,
} from 'lucide-react'
import { ConflictView } from '@/components/schedule/ConflictView'
import { DiffView } from '@/components/schedule/DiffView'
import { EntityClarifier } from '@/components/schedule/EntityClarifier'
import { ImpactView } from '@/components/schedule/ImpactView'
import { RuleChecklist } from '@/components/schedule/RuleChecklist'
import { ShiftDrawer } from '@/components/schedule/ShiftDrawer'
import { VersionHistory } from '@/components/schedule/VersionHistory'
import { WeekSelector } from '@/components/schedule/WeekSelector'
import { TopHeader } from '@/redesign/components/layout/TopHeader'
import { ScheduleViewToggle } from '@/redesign/components/schedule/ScheduleViewToggle'
import { ScheduleGrid } from '@/redesign/components/schedule/ScheduleGrid'
import { DateCoverageView } from '@/redesign/components/schedule/DateCoverageView'
import { DayDetailDrawer } from '@/redesign/components/schedule/DayDetailDrawer'
import { OverviewPanel } from '@/redesign/components/overview/OverviewPanel'
import { AttendanceCard } from '@/redesign/components/footer/AttendanceCard'
import { ActivityFeed } from '@/redesign/components/footer/ActivityFeed'
import { MobileSchedule } from '@/redesign/MobileSchedule'
import { AddShift } from '@/redesign/AddShift'
import { ShiftCoverageSummary } from '@/redesign/DateCoverage'
import { useWorkspace } from '@/redesign/useWorkspace'
import { calculateDayCoverage, calculateWeekMetrics } from '@/redesign/utils/scheduleSelectors'
import { addWeeks, isoWeekParts, weekLabel, weekRangeLabel } from '@/lib/isoWeek'
import { STATUS_LABELS } from '@/lib/presentation'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import type { Day, FeasibleResult, Schedule, ShiftType, TrustedAgentAction } from '@/types'
import type { DayCoverage } from '@/redesign/types/schedule'

export function ScheduleWorkbench() {
  const store = useAppStore()
  const agent = useAgentStore()
  const [view, setView] = useState<'employee' | 'date'>('employee')
  const [selectedDayForDrawer, setSelectedDayForDrawer] = useState<DayCoverage | null>(null)
  const [isDayDrawerOpen, setIsDayDrawerOpen] = useState(false)
  const [selectedDay, setSelectedDay] = useState<Day>('Mon')
  const [adding, setAdding] = useState<{ day: Day; shift: ShiftType; employeeId?: string } | null>(null)
  const [mobilePreview, setMobilePreview] = useState(false)
  const [isAnalysisExpanded, setIsAnalysisExpanded] = useState(true)

  const { rows, days } = useWorkspace()
  const busy =
    store.isRunning ||
    store.isLoadingWeek ||
    agent.isSending ||
    agent.isLoadingConversation ||
    !!store.isSavingEmployee

  const addShift = (day: Day, shift: ShiftType, employeeId?: string) => {
    if (busy || store.draftSchedule) return
    setIsDayDrawerOpen(false)
    setAdding({ day, shift, employeeId })
  }

  const active = store.activeSchedule
  const exceptionCount = store.result?.validation.authorized_violations?.length ?? 0

  const quickAction = (content: string, trustedAction?: TrustedAgentAction) => {
    void agent.openWithPrompt(
      content,
      trustedAction && { ...trustedAction, target_week: store.activeWeekStart }
    )
  }

  // Calculate day coverages and week metrics deterministically from real data
  const effectiveRules = store.result?.rule_config ?? store.ruleConfig
  const dayCoverages = useMemo(
    () => calculateDayCoverage(days, rows, effectiveRules, active?.assignments ?? [], store.result?.validation),
    [days, rows, effectiveRules, active, store.result?.validation]
  )

  const activeSelectedDay = useMemo(() => {
    return dayCoverages.find((d) => d.day === selectedDay) || dayCoverages[0] || null
  }, [dayCoverages, selectedDay])

  const activeDayForDrawer = useMemo(() => {
    if (!selectedDayForDrawer) return null
    return dayCoverages.find((d) => d.fullDate === selectedDayForDrawer.fullDate) ?? null
  }, [dayCoverages, selectedDayForDrawer])

  const weekMetrics = useMemo(
    () => calculateWeekMetrics(dayCoverages, rows),
    [dayCoverages, rows]
  )

  if (store.isBootstrapping) {
    return (
      <div className="grid min-h-[60vh] place-items-center">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600" />
          <p className="mt-4 text-sm font-semibold text-slate-500">
            正在读取员工、规则和正式排班…
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1600px] w-full mx-auto bg-white/95 rounded-[36px] p-5 md:p-7 shadow-soft border border-slate-200/70 flex flex-col gap-5">
      {/* Top Header Bar */}
      <TopHeader
        activeTabTitle="排班工作台"
        currentWeekText={weekLabel(store.activeWeekStart)}
        subTitle={
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
            <span className="font-extrabold text-slate-700">{weekLabel(store.activeWeekStart)}</span>
            {active ? (
              <h2 className="text-xs font-extrabold text-slate-700">
                {weekLabel(store.activeWeekStart)} · v{active.version}{' '}
                <span
                  className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    active.status === 'confirmed'
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-amber-100 text-amber-700'
                  }`}
                >
                  {STATUS_LABELS[active.status]}
                </span>
              </h2>
            ) : null}
            <span>
              {weekRangeLabel(store.activeWeekStart)}
              {active ? ` · v${active.version} · ${STATUS_LABELS[active.status]}` : ' · 未生成'}
            </span>
            {exceptionCount > 0 && (
              <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-bold text-amber-700 border border-amber-200">
                存在 {exceptionCount} 项已授权规则例外
              </span>
            )}
          </div>
        }
        weekSelector={
          <WeekSelector
            activeWeekStart={store.activeWeekStart}
            weeks={store.weekOptions}
            disabled={busy}
            onSelect={(weekStart) => void store.setActiveWeek(weekStart)}
          />
        }
        onPrevWeek={() => void store.setActiveWeek(addWeeks(store.activeWeekStart, -1))}
        onNextWeek={() => void store.setActiveWeek(addWeeks(store.activeWeekStart, 1))}
        addShiftDisabled={busy || !!store.draftSchedule}
        onAddShift={() => addShift(selectedDay, 'morning')}
        onToggleMobilePreview={() => setMobilePreview((prev) => !prev)}
        showMobilePreview={mobilePreview}
        onOpenCopilot={() => agent.openChat()}
      />

      {/* Infeasible Conflict Diagnostics View */}
      {store.infeasibleResult && (
        <ConflictView result={store.infeasibleResult} employees={store.employees} />
      )}

      {/* Week Data Loading Indicator */}
      {store.isLoadingWeek && (
        <div className="flex items-center justify-center gap-2 p-12 text-sm font-semibold text-slate-500">
          <LoaderCircle className="h-5 w-5 animate-spin text-blue-600" />
          正在读取这一周的排班…
        </div>
      )}

      {/* Active Schedule Section */}
      {!store.isLoadingWeek && active ? (
        <>
          {/* View Mode Toggle: [ 👤 员工视图 ] [ 📅 日期视图 ] */}
          <ScheduleViewToggle
            viewMode={view}
            onViewModeChange={setView}
            totalGaps={weekMetrics.totalGaps}
            employeeCountText={`全员 ${rows.length} 名员工在册`}
          />

          {/* Main Content Area: Left Schedule View + Right Overview Panel */}
          <div className="flex flex-col xl:flex-row gap-6 items-start">
            <div className="flex-1 min-w-0 w-full">
              {view === 'employee' ? (
                <ScheduleGrid
                  scheduleData={rows}
                  daysHeader={days}
                  renderDaySummary={(day) => <ShiftCoverageSummary day={day as Day} />}
                  onSelectEmployee={(e) => { setIsDayDrawerOpen(false); store.selectEmployee(e.id) }}
                  onShiftClick={(id, shift) => {
                    if (shift.shiftType === 'morning' || shift.shiftType === 'evening') {
                      store.selectShift({ day: shift.day as Day, shift: shift.shiftType })
                    } else if (!busy && !store.draftSchedule) {
                      addShift(shift.day as Day, 'morning', id)
                    }
                  }}
                  onSwapClick={() => {
                    void agent.openWithPrompt(
                      '张宇 (E02) 与 孙静 (E05) 申请周五班次互换，请分析互换影响及规则合规性。',
                      { intent: 'advice', target_week: store.activeWeekStart }
                    )
                  }}
                />
              ) : (
                <DateCoverageView
                  addShiftDisabled={busy || !!store.draftSchedule}
                  aiDisabled={busy}
                  dayCoverages={dayCoverages}
                  selectedDate={activeSelectedDay}
                  onSelectDay={(day) => setSelectedDay(day.day as Day)}
                  onAddShiftForSlot={(date, shiftType) => {
                    const day = dayCoverages.find((item) => item.fullDate === date)
                    if (day) addShift(day.day as Day, shiftType)
                  }}
                  onAskAiForDay={(day, shift) => {
                    const shiftLabel = shift ? shift.shiftName : '全天'
                    void agent.openWithPrompt(
                      `分析 ${day.fullDate}（${day.dayCn}）${shiftLabel}的人员覆盖与规则冲突，并给出调整建议。`,
                      { intent: 'advice', target_week: store.activeWeekStart }
                    )
                  }}
                  onSelectEmployee={(e) => { setIsDayDrawerOpen(false); store.selectEmployee(e.id) }}
                />
              )}
            </div>

            {/* Right Side: Overview & Real Metrics Panel */}
            <OverviewPanel
              weekMetrics={weekMetrics}
              onSelectAlert={(alert) => {
                if (alert.day) {
                  const targetDay = alert.day as Day
                  setSelectedDay(targetDay)
                  const day = dayCoverages.find((d) => d.day === targetDay)
                  if (day) {
                    setSelectedDayForDrawer(day)
                    setIsDayDrawerOpen(true)
                  }
                }
              }}
              onViewAllRules={() => store.setPage('rules')}
            />
          </div>

          {/* Attendance & Activity Companion Cards */}
          <div className="flex flex-col md:flex-row gap-5 pt-2 border-t border-slate-100">
            <AttendanceCard metrics={weekMetrics} />
            <ActivityFeed versions={store.versions} />
          </div>

          {/* Section 4: 次级业务支撑区 (放置于底部，兼顾 E2E 与历史追溯) */}
          {store.draftSchedule && (
            <DraftConfirmBanner
              draft={store.draftSchedule}
              result={store.result}
              exceptionCount={exceptionCount}
              busy={busy}
              onConfirm={() => void store.confirmDraft()}
              onCancel={() => void store.cancelDraft()}
            />
          )}

          {/* AI Quick Actions Bar */}
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="eyebrow">快捷操作</p>
                <h3 className="mt-0.5 text-sm font-extrabold text-slate-800">
                  让 AI 从当前周开始
                </h3>
              </div>
              <MessageCircleMore className="h-4 w-4 text-blue-600" />
            </div>
            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
              <QuickAction
                icon={CalendarPlus}
                label="生成新排班"
                detail="创建当前周草稿"
                disabled={busy || !!store.draftSchedule}
                onClick={() =>
                  quickAction('帮我生成当前周排班，尽量满足员工早晚班偏好。', {
                    intent: 'generate',
                  })
                }
              />
              <QuickAction
                icon={Umbrella}
                label="E02 临时请假"
                detail="周五请假并最小调整"
                disabled={
                  busy ||
                  !!store.draftSchedule ||
                  !store.confirmedSchedule ||
                  !store.employees.some((e) => e.id === 'E02')
                }
                onClick={() =>
                  quickAction(
                    'E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。',
                    {
                      intent: 'replan',
                      changes: [{ employee_id: 'E02', type: 'leave', day: 'Fri' }],
                      minimize_changes: true,
                    }
                  )
                }
              />
              <QuickAction
                icon={BarChart3}
                label="分析优化空间"
                detail="只分析，不修改排班"
                disabled={busy}
                onClick={() =>
                  quickAction('这周排班有什么可以优化的吗？', { intent: 'advice' })
                }
              />
              <QuickAction
                icon={ShieldCheck}
                label="检查排班规则"
                detail="运行确定性校验"
                disabled={busy}
                onClick={() =>
                  quickAction('帮我检查当前排班有没有违反规则。', {
                    intent: 'validate',
                  })
                }
              />
            </div>
          </div>

          {/* Secondary Details: Metrics, Diff, Impact, Checklist & Version History (Collapsible Panel) */}
          <div className="mt-2 border-t border-slate-150 pt-4">
            <button
              type="button"
              onClick={() => setIsAnalysisExpanded((prev) => !prev)}
              className="flex w-full items-center justify-between rounded-2xl bg-slate-50/80 px-4 py-3 border border-slate-200/80 hover:bg-slate-100/80 transition text-left"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-700">
                  {isAnalysisExpanded
                    ? '收起排班深度分析与版本历史 (E2E/诊断)'
                    : '展开排班深度分析与版本历史 (E2E/诊断)'}
                </span>
                <span className="text-[10px] font-semibold text-slate-400 bg-white border border-slate-200 px-1.5 py-0.5 rounded">
                  诊断与溯源
                </span>
              </div>
              {isAnalysisExpanded ? (
                <ChevronUp className="h-4 w-4 text-slate-400" />
              ) : (
                <ChevronDown className="h-4 w-4 text-slate-400" />
              )}
            </button>

            {isAnalysisExpanded && (
              <div className="mt-4 space-y-6 animate-fade-in">
                <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
                  <div className="space-y-6">
                    <Metrics result={store.result} schedule={active} />
                    {store.draftSchedule && store.confirmedSchedule && (
                      <DiffView diff={store.result?.diff} />
                    )}
                    <ImpactView impact={store.result?.impact} />
                  </div>
                  <div className="space-y-6">
                    <RuleChecklist validation={store.result?.validation ?? null} />
                    <VersionHistory versions={store.versions} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        !store.isLoadingWeek &&
        (
          <div className="grid min-h-[380px] place-items-center rounded-3xl border-2 border-dashed border-slate-200 bg-slate-50/50 p-8 text-center">
            <div className="max-w-md space-y-4">
              <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-blue-50 text-blue-600 shadow-sm">
                <CalendarDays className="h-7 w-7" />
              </span>
              <div>
                <h2 className="text-lg font-extrabold text-slate-800">这一周还没有排班</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  点击“生成新排班”让 AI 读取当前周上下文，并由确定性求解器创建待确认草稿。
                </p>
              </div>
              <div className="pt-2">
                <button
                  type="button"
                  disabled={busy || !!store.draftSchedule}
                  onClick={() =>
                    quickAction('帮我生成当前周排班，尽量满足员工早晚班偏好。', {
                      intent: 'generate',
                    })
                  }
                  className="btn-primary inline-flex items-center gap-2"
                >
                  <CalendarPlus className="h-4 w-4" />
                  <span>生成新排班</span>
                </button>
              </div>
            </div>
          </div>
        )
      )}

      {/* Interactive Drawers & Dialogs */}
      <DayDetailDrawer
        addShiftDisabled={busy || !!store.draftSchedule}
        aiDisabled={busy}
        day={activeDayForDrawer}
        isOpen={isDayDrawerOpen && !store.isLoadingWeek}
        onClose={() => setIsDayDrawerOpen(false)}
        onAddShiftForSlot={(date, shiftType) => {
          const targetDayCoverage = dayCoverages.find((d) => d.fullDate === date)
          const targetDay = (targetDayCoverage?.day || selectedDay) as Day
          addShift(targetDay, shiftType)
        }}
        onAskAiForDay={(day, shift) => {
          if (busy) return
          setIsDayDrawerOpen(false)
          const shiftLabel = shift ? shift.shiftName : '全天'
          void agent.openWithPrompt(
            `帮我分析第${isoWeekParts(store.activeWeekStart).isoWeek}周${day.dayCn}${shiftLabel}的排班缺口，并给出满足硬约束的调整方案。`,
            { intent: 'advice', target_week: store.activeWeekStart }
          )
        }}
        onSelectEmployee={(e) => { setIsDayDrawerOpen(false); store.selectEmployee(e.id) }}
        onViewConflicts={() => {
          setView('date')
          setIsDayDrawerOpen(false)
        }}
      />

      {adding && (
        <AddShift
          key={store.activeWeekStart}
          initialDay={adding.day}
          initialShift={adding.shift}
          initialEmployee={adding.employeeId}
          onClose={() => setAdding(null)}
        />
      )}

      <ShiftDrawer
        selection={store.selectedShift}
        schedule={active}
        employees={store.employees}
        validation={store.result?.validation}
        onClose={() => store.selectShift(null)}
      />

      <EntityClarifier
        clarification={store.clarification}
        onChoose={(id) => void store.resolveClarification(id)}
        onClose={store.dismissClarification}
      />

      {mobilePreview && <MobileSchedule onClose={() => setMobilePreview(false)} />}
    </div>
  )
}

function QuickAction({
  icon: Icon,
  label,
  detail,
  disabled,
  onClick,
}: {
  icon: typeof CalendarPlus
  label: string
  detail: string
  disabled: boolean
  onClick(): void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-3 rounded-2xl border border-slate-200/90 bg-white p-3 text-left transition hover:border-blue-300 hover:bg-blue-50/40 disabled:cursor-not-allowed disabled:opacity-50 shadow-2xs group"
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-600 group-hover:bg-blue-600 group-hover:text-white transition">
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-xs font-bold text-slate-800 truncate">{label}</span>
        <span className="block text-[10px] text-slate-400 truncate">{detail}</span>
      </span>
    </button>
  )
}

function Metrics({
  result,
  schedule,
}: {
  result: ReturnType<typeof useAppStore>['result']
  schedule: NonNullable<ReturnType<typeof useAppStore>['activeSchedule']>
}) {
  const metrics = result?.metrics
  const items = [
    {
      icon: BarChart3,
      label: '偏好满足率',
      value: metrics ? `${Math.round(metrics.preference_rate * 100)}%` : '—',
    },
    {
      icon: ListChecks,
      label: '工作量差距',
      value: metrics ? `${metrics.workload_gap} 班` : '—',
    },
    {
      icon: GitCompareArrows,
      label: '调整记录数',
      value: metrics ? `${metrics.changed_assignments} 条` : '—',
    },
    {
      icon: CalendarDays,
      label: '版本与状态',
      value: `v${schedule.version} · ${STATUS_LABELS[schedule.status]}`,
    },
  ]
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map(({ icon: Icon, label, value }) => (
        <div
          key={label}
          className="flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white p-3.5 shadow-2xs"
        >
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-100 text-slate-600">
            <Icon className="h-4 w-4" />
          </span>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
              {label}
            </p>
            <p className="mt-0.5 text-base font-extrabold text-slate-900">{value}</p>
          </div>
        </div>
      ))}
    </section>
  )
}

function DraftConfirmBanner({
  draft,
  result,
  exceptionCount,
  busy,
  onConfirm,
  onCancel,
}: {
  draft: Schedule
  result: FeasibleResult | null
  exceptionCount: number
  busy: boolean
  onConfirm(): void
  onCancel(): void
}) {
  const isConfirmable = result?.validation.confirmable ?? result?.validation.passed ?? false
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-amber-300 bg-amber-50/90 p-4 sm:flex-row sm:items-center shadow-xs">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-extrabold text-amber-900">
          草稿版本 {draft.version} 等待确认
        </p>
        <p className="mt-0.5 text-xs text-amber-700">
          {result?.validation.employee_data_stale || result?.validation.rules_data_stale
            ? '员工资料或标准规则已变更，请取消此草稿后重新生成。'
            : exceptionCount
            ? `存在 ${exceptionCount} 项已授权规则例外。确认后，该版本将携带这些例外正式生效。`
            : isConfirmable
            ? '确认后该排班版本正式生效。'
            : '存在未授权规则冲突，不能确认。'}
        </p>
      </div>
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="btn-secondary"
        >
          <X className="h-4 w-4" />
          取消
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy || !isConfirmable}
          className="btn-primary"
        >
          <Check className="h-4 w-4" />
          {exceptionCount ? '确认含例外的排班' : '确认变更'}
        </button>
      </div>
    </section>
  )
}
