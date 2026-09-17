import { ArrowRight, Equal, Minus, Plus } from 'lucide-react'
import { DAY_LABELS, SHIFT_LABELS } from '@/lib/presentation'
import type { ScheduleDiff } from '@/types'

export function DiffView({ diff }: { diff: ScheduleDiff | null | undefined }) {
  if (!diff || diff.changed_shifts === 0) {
    return (
      <section className="panel p-5">
        <p className="eyebrow">排班变更对比</p>
        <p className="mt-3 text-sm font-semibold text-emerald-700">没有班次发生变化。</p>
      </section>
    )
  }
  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-4">
        <p className="eyebrow">变更明细</p>
        <h3 className="mt-1 text-base font-extrabold text-ink">正式排班 <ArrowRight className="mx-1 inline h-4 w-4" /> 待确认草稿</h3>
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
        {diff.shifts.map((item) => (
          <div key={`${item.day}-${item.shift}`} className="rounded-xl border border-slate-200 p-3">
            <p className="text-xs font-extrabold text-slate-700">{DAY_LABELS[item.day]} · {SHIFT_LABELS[item.shift]}</p>
            <div className="mt-2 space-y-1">
              {item.removed.map((id) => <p key={`-${id}`} className="flex items-center gap-2 text-xs font-semibold text-red-600"><Minus className="h-3 w-3" />{id}</p>)}
              {item.added.map((id) => <p key={`+${id}`} className="flex items-center gap-2 text-xs font-semibold text-emerald-700"><Plus className="h-3 w-3" />{id}</p>)}
              {item.unchanged?.map((id) => <p key={`=${id}`} className="flex items-center gap-2 text-xs font-medium text-slate-400"><Equal className="h-3 w-3" />{id}</p>)}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
