import { useState } from 'react'
import { BarChart3, CalendarDays, Check, GitCompareArrows, LayoutGrid, ListChecks, Users, X } from 'lucide-react'
import { ActionSelector } from '@/components/schedule/ActionSelector'
import { ConflictView } from '@/components/schedule/ConflictView'
import { DiffView } from '@/components/schedule/DiffView'
import { EmployeeView } from '@/components/schedule/EmployeeView'
import { EntityClarifier } from '@/components/schedule/EntityClarifier'
import { ImpactView } from '@/components/schedule/ImpactView'
import { PresetChips, type PresetId } from '@/components/schedule/PresetChips'
import { PromptBox } from '@/components/schedule/PromptBox'
import { RuleChecklist } from '@/components/schedule/RuleChecklist'
import { ScheduleGrid } from '@/components/schedule/ScheduleGrid'
import { ShiftDrawer } from '@/components/schedule/ShiftDrawer'
import { VersionHistory } from '@/components/schedule/VersionHistory'
import { useAppStore } from '@/store/AppStore'
import type { RunAction, ScheduleView } from '@/types'

const prompts: Record<RunAction, string> = {
  generate: '帮我生成本周排班，尽量满足员工早晚班偏好。',
  leave: 'E02 周五临时请假，重新排班，其他员工尽量少调整。',
  freeform: '',
}

export function ScheduleWorkbench() {
  const store = useAppStore()
  const [action, setAction] = useState<RunAction>('generate')
  const [prompt, setPrompt] = useState(prompts.generate)
  const [view, setView] = useState<ScheduleView>('shift')
  const active = store.activeSchedule
  const [weekStart] = useState(currentMonday)

  const chooseAction = (next: RunAction) => {
    setAction(next)
    setPrompt(prompts[next])
  }

  const run = () => {
    if (action === 'generate' || (!store.confirmedSchedule && action === 'freeform')) {
      void store.generate(prompt, weekStart)
      return
    }
    if (action === 'freeform' && /生成|generate/i.test(prompt)) {
      void store.generate(prompt, weekStart)
      return
    }
    void store.replan(prompt, [])
  }

  const runPreset = (preset: PresetId) => {
    if (preset === 'normal') {
      chooseAction('generate')
      void store.generate(prompts.generate, weekStart)
    } else if (preset === 'leave') {
      chooseAction('leave')
      void store.replan(prompts.leave, [{ employee_id: 'E02', type: 'leave', day: 'Fri' }])
    } else {
      const text = '周日所有店长请假，检查排班是否可行。'
      setAction('freeform')
      setPrompt(text)
      void store.generate(text, weekStart)
    }
  }

  if (store.isBootstrapping) {
    return <div className="grid min-h-[60vh] place-items-center"><div className="text-center"><div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-teal-100 border-t-teal-600" /><p className="mt-4 text-sm font-semibold text-slate-500">正在读取员工、规则和正式排班…</p></div></div>
  }

  return (
    <div className="space-y-6">
      <section className="panel p-5 lg:p-6">
        <div className="mb-5"><p className="eyebrow">AI Scheduling Command</p><h2 className="mt-1 text-xl font-extrabold tracking-tight text-ink">你想做什么？</h2></div>
        <ActionSelector value={action} onChange={chooseAction} />
        <div className="mt-4"><PromptBox value={prompt} onChange={setPrompt} onRun={run} running={store.isRunning} /></div>
        <div className="mt-4 border-t border-slate-100 pt-4"><p className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">Demo Presets · 真实求解路径</p><PresetChips onSelect={runPreset} disabled={store.isRunning} /></div>
      </section>

      {store.infeasibleResult && <ConflictView result={store.infeasibleResult} />}

      {active ? (
        <>
          {store.draftSchedule && (
            <section className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className="text-sm font-extrabold text-amber-900">Draft v{store.draftSchedule.version} 等待确认</p><p className="text-xs text-amber-700">正式排班保持不变。Validator 通过后才可确认。</p></div>
              <div className="flex gap-2"><button onClick={() => void store.cancelDraft()} disabled={store.isRunning} className="btn-secondary"><X className="h-4 w-4" />取消</button><button onClick={() => void store.confirmDraft()} disabled={store.isRunning || !store.result?.validation.passed} className="btn-primary"><Check className="h-4 w-4" />确认变更</button></div>
            </section>
          )}

          <section className="panel overflow-hidden">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><p className="eyebrow">Weekly Schedule</p><h2 className="mt-1 text-lg font-extrabold text-ink">{active.week_start} · v{active.version} <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] uppercase ${active.status === 'confirmed' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{active.status}</span></h2></div>
              <div className="flex rounded-xl bg-slate-100 p-1"><ViewButton active={view === 'shift'} onClick={() => setView('shift')} icon={LayoutGrid} label="班次视角" /><ViewButton active={view === 'employee'} onClick={() => setView('employee')} icon={Users} label="员工视角" /></div>
            </div>
            <div className="p-4 lg:p-5">{view === 'shift' ? <ScheduleGrid schedule={active} employees={store.employees} onSelectShift={(day, shift) => store.selectShift({ day, shift })} /> : <EmployeeView schedule={active} employees={store.employees} />}</div>
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
      ) : !store.infeasibleResult && (
        <section className="panel grid min-h-[340px] place-items-center border-dashed p-8 text-center">
          <div><span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-teal-50 text-teal-700"><CalendarDays className="h-7 w-7" /></span><h2 className="mt-4 text-lg font-extrabold text-ink">还没有排班</h2><p className="mt-2 max-w-md text-sm leading-6 text-slate-500">运行“正常生成”预设，后端会构建上下文、调用 CP-SAT、独立校验并保存 draft。</p></div>
        </section>
      )}

      <ShiftDrawer selection={store.selectedShift} schedule={active} employees={store.employees} onClose={() => store.selectShift(null)} />
      <EntityClarifier clarification={store.clarification} onChoose={(id) => void store.resolveClarification(id)} onClose={store.dismissClarification} />
    </div>
  )
}

function ViewButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick(): void; icon: typeof LayoutGrid; label: string }) {
  return <button onClick={onClick} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold transition ${active ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500'}`}><Icon className="h-4 w-4" />{label}</button>
}

function Metrics({ result, schedule }: { result: ReturnType<typeof useAppStore>['result']; schedule: NonNullable<ReturnType<typeof useAppStore>['activeSchedule']> }) {
  const metrics = result?.metrics
  const items = [
    { icon: BarChart3, label: 'Preference Rate', value: metrics ? `${Math.round(metrics.preference_rate * 100)}%` : '—' },
    { icon: ListChecks, label: 'Workload Gap', value: metrics ? String(metrics.workload_gap) : '—' },
    { icon: GitCompareArrows, label: 'Changes', value: metrics ? String(metrics.changed_assignments) : '—' },
    { icon: CalendarDays, label: 'Version / Status', value: `v${schedule.version} · ${schedule.status}` },
  ]
  return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{items.map(({ icon: Icon, label, value }) => <div key={label} className="panel flex items-center gap-3 p-4"><span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-600"><Icon className="h-5 w-5" /></span><div><p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 text-lg font-black text-ink">{value}</p></div></div>)}</section>
}

function currentMonday() {
  const now = new Date()
  const offset = (now.getDay() + 6) % 7
  now.setDate(now.getDate() - offset)
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
