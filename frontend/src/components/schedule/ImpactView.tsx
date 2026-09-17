import { CircleDot, GitBranch, Users } from 'lucide-react'
import { shiftReference } from '@/lib/presentation'
import type { ImpactRadius } from '@/types'

function labels(items: ImpactRadius['direct_changes']) {
  return items.map(shiftReference).join('、') || '无'
}

export function ImpactView({ impact }: { impact: ImpactRadius | null | undefined }) {
  if (!impact) return null
  return (
    <section className="panel p-5">
      <p className="eyebrow">调整影响范围</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Metric icon={CircleDot} label="直接变更" value={labels(impact.direct_changes)} tone="text-blue-700 bg-blue-50" />
        <Metric icon={GitBranch} label="连带变更" value={labels(impact.related_changes)} tone="text-amber-700 bg-amber-50" />
        <Metric icon={Users} label="未变化班次" value={`${impact.unchanged_shifts} / ${impact.total_shifts ?? 14}`} tone="text-emerald-700 bg-emerald-50" />
      </div>
    </section>
  )
}

function Metric({ icon: Icon, label, value, tone }: { icon: typeof CircleDot; label: string; value: string; tone: string }) {
  return <div className="rounded-xl border border-slate-200 p-3"><span className={`mb-2 grid h-8 w-8 place-items-center rounded-lg ${tone}`}><Icon className="h-4 w-4" /></span><p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 break-words text-sm font-extrabold text-slate-700">{value}</p></div>
}
