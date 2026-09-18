import { useState } from 'react'
import { BarChart3, CalendarDays, CalendarPlus, Check, GitCompareArrows, LayoutGrid, ListChecks, LoaderCircle, MessageCircleMore, ShieldCheck, Umbrella, Users, X } from 'lucide-react'
import { ConflictView } from '@/components/schedule/ConflictView'
import { DiffView } from '@/components/schedule/DiffView'
import { EmployeeView } from '@/components/schedule/EmployeeView'
import { EntityClarifier } from '@/components/schedule/EntityClarifier'
import { ImpactView } from '@/components/schedule/ImpactView'
import { RuleChecklist } from '@/components/schedule/RuleChecklist'
import { ScheduleGrid } from '@/components/schedule/ScheduleGrid'
import { ShiftDrawer } from '@/components/schedule/ShiftDrawer'
import { VersionHistory } from '@/components/schedule/VersionHistory'
import { WeekSelector } from '@/components/schedule/WeekSelector'
import { weekLabel, weekRangeLabel } from '@/lib/isoWeek'
import { STATUS_LABELS } from '@/lib/presentation'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import type { ScheduleView, TrustedAgentAction } from '@/types'

export function ScheduleWorkbench() {
  const store = useAppStore()
  const agent = useAgentStore()
  const [view, setView] = useState<ScheduleView>('shift')
  const active = store.activeSchedule
  const exceptionCount = store.result?.validation.authorized_violations?.length ?? 0

  const quickAction = (content: string, trustedAction?: TrustedAgentAction) => {
    void agent.openWithPrompt(content, trustedAction && { ...trustedAction, target_week: store.activeWeekStart })
  }

  if (store.isBootstrapping) {
    return <div className="grid min-h-[60vh] place-items-center"><div className="text-center"><div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-teal-100 border-t-teal-600" /><p className="mt-4 text-sm font-semibold text-slate-500">正在读取员工、规则和正式排班…</p></div></div>
  }

  return (
    <div className="space-y-6">
      <section className="panel flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="eyebrow">排班周次</p>
          <h2 className="mt-1 text-xl font-extrabold tracking-tight text-ink">{weekLabel(store.activeWeekStart)}</h2>
          <p className="mt-1 text-sm font-semibold text-slate-500">{weekRangeLabel(store.activeWeekStart)}{active ? ` · v${active.version} · ${STATUS_LABELS[active.status]}` : ' · 未生成'}</p>
          {exceptionCount > 0 && <p className="mt-2 text-sm font-bold text-amber-700">存在 {exceptionCount} 项已授权规则例外</p>}
        </div>
        <WeekSelector activeWeekStart={store.activeWeekStart} weeks={store.weekOptions} disabled={store.isLoadingWeek || store.isRunning} onSelect={(weekStart) => void store.setActiveWeek(weekStart)} />
      </section>

      <section className="panel p-4 lg:p-5">
        <div className="mb-3 flex items-center justify-between"><div><p className="eyebrow">快捷操作</p><h2 className="mt-1 text-base font-extrabold text-ink">让 AI 从当前周开始</h2></div><MessageCircleMore className="h-5 w-5 text-teal-600" /></div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <QuickAction icon={CalendarPlus} label="生成新排班" detail="创建当前周草稿" disabled={agent.isSending} onClick={() => quickAction('帮我生成当前周排班，尽量满足员工早晚班偏好。', { intent: 'generate' })} />
          <QuickAction icon={Umbrella} label="E02 临时请假" detail="周五请假并最小调整" disabled={agent.isSending} onClick={() => quickAction('E02 周五临时请假，帮我重新排一下，其他员工尽量少调整。', { intent: 'replan', changes: [{ employee_id: 'E02', type: 'leave', day: 'Fri' }], minimize_changes: true })} />
          <QuickAction icon={BarChart3} label="分析优化空间" detail="只分析，不修改排班" disabled={agent.isSending} onClick={() => quickAction('这周排班有什么可以优化的吗？', { intent: 'advice' })} />
          <QuickAction icon={ShieldCheck} label="检查排班规则" detail="运行确定性校验" disabled={agent.isSending} onClick={() => quickAction('帮我检查当前排班有没有违反规则。', { intent: 'validate' })} />
        </div>
      </section>

      {store.isLoadingWeek && <section className="panel flex items-center justify-center gap-2 p-8 text-sm font-semibold text-slate-500"><LoaderCircle className="h-5 w-5 animate-spin text-teal-600" />正在读取这一周的排班…</section>}
      {store.infeasibleResult && <ConflictView result={store.infeasibleResult} employees={store.employees} />}

      {!store.isLoadingWeek && active ? (
        <>
          {store.draftSchedule && (
            <section className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className="text-sm font-extrabold text-amber-900">草稿版本 {store.draftSchedule.version} 等待确认</p><p className="text-xs text-amber-700">{exceptionCount ? `存在 ${exceptionCount} 项已授权规则例外。确认后，该版本将携带这些例外正式生效。` : (store.result?.validation.confirmable ?? store.result?.validation.passed) ? '确认后该排班版本正式生效。' : '存在未授权规则冲突，不能确认。'}</p></div>
              <div className="flex gap-2"><button onClick={() => void store.cancelDraft()} disabled={store.isRunning} className="btn-secondary"><X className="h-4 w-4" />取消</button><button onClick={() => void store.confirmDraft()} disabled={store.isRunning || !(store.result?.validation.confirmable ?? store.result?.validation.passed)} className="btn-primary"><Check className="h-4 w-4" />{exceptionCount ? '确认含例外的排班' : '确认变更'}</button></div>
            </section>
          )}

          <section className="panel overflow-hidden">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className="eyebrow">排班结果</p><h2 className="mt-1 text-lg font-extrabold text-ink">{weekLabel(active.week_start)} · v{active.version} <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${active.status === 'confirmed' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{STATUS_LABELS[active.status]}</span></h2></div>
              <div className="flex rounded-xl bg-slate-100 p-1"><ViewButton active={view === 'shift'} onClick={() => setView('shift')} icon={LayoutGrid} label="班次视角" /><ViewButton active={view === 'employee'} onClick={() => setView('employee')} icon={Users} label="员工视角" /></div>
            </div>
            <div className="p-4 lg:p-5">{view === 'shift' ? <ScheduleGrid schedule={active} employees={store.employees} validation={store.result?.validation} onSelectShift={(day, shift) => store.selectShift({ day, shift })} /> : <EmployeeView schedule={active} employees={store.employees} />}</div>
          </section>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-5">
              <Metrics result={store.result} schedule={active} />
              {store.draftSchedule && store.confirmedSchedule && <DiffView diff={store.result?.diff} />}
              <ImpactView impact={store.result?.impact} />
            </div>
            <div className="space-y-5"><RuleChecklist validation={store.result?.validation ?? null} /><VersionHistory versions={store.versions} /></div>
          </div>
        </>
      ) : !store.isLoadingWeek && !store.infeasibleResult && (
        <section className="panel grid min-h-[340px] place-items-center border-dashed p-8 text-center">
          <div><span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-teal-50 text-teal-700"><CalendarDays className="h-7 w-7" /></span><h2 className="mt-4 text-lg font-extrabold text-ink">这一周还没有排班</h2><p className="mt-2 max-w-md text-sm leading-6 text-slate-500">点击“生成新排班”让 AI 读取当前周上下文，并由确定性求解器创建待确认草稿。</p></div>
        </section>
      )}

      <ShiftDrawer selection={store.selectedShift} schedule={active} employees={store.employees} validation={store.result?.validation} onClose={() => store.selectShift(null)} />
      <EntityClarifier clarification={store.clarification} onChoose={(id) => void store.resolveClarification(id)} onClose={store.dismissClarification} />
    </div>
  )
}

function QuickAction({ icon: Icon, label, detail, disabled, onClick }: { icon: typeof CalendarPlus; label: string; detail: string; disabled: boolean; onClick(): void }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-teal-300 hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-teal-50 text-teal-700"><Icon className="h-[18px] w-[18px]" /></span><span><span className="block text-sm font-extrabold text-slate-800">{label}</span><span className="block text-[11px] text-slate-500">{detail}</span></span></button>
}

function ViewButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick(): void; icon: typeof LayoutGrid; label: string }) {
  return <button onClick={onClick} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold transition ${active ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500'}`}><Icon className="h-4 w-4" />{label}</button>
}

function Metrics({ result, schedule }: { result: ReturnType<typeof useAppStore>['result']; schedule: NonNullable<ReturnType<typeof useAppStore>['activeSchedule']> }) {
  const metrics = result?.metrics
  const items = [
    { icon: BarChart3, label: '偏好满足率', value: metrics ? `${Math.round(metrics.preference_rate * 100)}%` : '—' },
    { icon: ListChecks, label: '工作量差距', value: metrics ? `${metrics.workload_gap} 班` : '—' },
    { icon: GitCompareArrows, label: '调整记录数', value: metrics ? `${metrics.changed_assignments} 条` : '—' },
    { icon: CalendarDays, label: '版本与状态', value: `v${schedule.version} · ${STATUS_LABELS[schedule.status]}` },
  ]
  return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{items.map(({ icon: Icon, label, value }) => <div key={label} className="panel flex items-center gap-3 p-4"><span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-600"><Icon className="h-5 w-5" /></span><div><p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 text-lg font-black text-ink">{value}</p></div></div>)}</section>
}
